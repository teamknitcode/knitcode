"""JARVIS benchmark: KnitCode vs. the JARVIS ground truth (and PyCG / JARVIS outputs).

Data, ground truth and the reference tool outputs come from the JARVIS artifact
(https://github.com/pythonJaRvis/pythonJaRvis.github.io, directory `Jarvis/`).

Usage:
    python scripts/jarvis_benchmark.py micro --jarvis ../pythonJaRvis.github.io/Jarvis --output out/jarvis/micro.json
    python scripts/jarvis_benchmark.py macro --jarvis ../pythonJaRvis.github.io/Jarvis --output out/jarvis/macro
    # an older engine, same adapter and scorer:
    python scripts/jarvis_benchmark.py macro --jarvis ... --output out/old --engine-root ../knitcode-old

Scoring follows the artifact's reproducing_RQ2/gen_table.py exactly:
  TP = per caller, |predicted callees & true callees|   (callers absent from truth add no TP)
  FP = |predicted edges| - TP,   FN = |true edges| - TP
  micro:  C. (complete) = no FP,  S. (sound) = no FN
  macro:  precision = TP / (TP + FP), recall = TP / |true edges|   (E.A. mode)

E.A. = every function is an entry point, application code only. In this mode the
ground truth, PyCG and JARVIS contain application functions plus builtins written
as `<builtin>.f`, `<str>.m`, `<list>.m`, `<map>.m` (dict). KnitCode output is put in
the same notation, and calls into other libraries (os, re, ...) are dropped
(`--keep-library-calls` keeps them, for a raw score). No ground-truth-driven
renaming or edge deletion is done.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_DIR))
# --engine-root scores an archived engine (e.g. a `git worktree` of an older
# commit) with this adapter; each version runs in its own process.
_engine = argparse.ArgumentParser(add_help=False)
_engine.add_argument('--engine-root', type=Path)
ENGINE_ROOT = _engine.parse_known_args()[0].engine_root
if ENGINE_ROOT:
    sys.path.insert(0, str(ENGINE_ROOT.resolve()))

from pycg_adapter import adjacency, pycg_scope, to_pycg  # noqa: E402

# project -> (ground-truth dir, --package root, analyzed files relative to that root),
# the same inputs as reproducing_RQ12_setup/macro_benchmark/pycg_EA.sh.
MACRO = {
    'bpytop': ('bpytop', 'bpytop', ['bpytop.py']),
    'sqlparse': ('sqlparse', 'sqlparse', ['sqlparse/**/*.py']),
    'TextRank4ZH': ('TextRank4ZH', 'TextRank4ZH', ['textrank4zh/*.py']),
    'furl': ('furl', 'furl', ['furl/*.py']),
    'rich-cli': ('rich-cli', 'rich-cli/src', ['rich_cli/*.py']),
    'sshtunnel': ('sshtunnel', 'sshtunnel', ['sshtunnel.py']),
}
# Reference outputs shipped in the artifact (reproducing_RQ2/macro_benchmark/<dir>/...).
REFERENCE = {'PyCG E.A.(1)': 'pycg/pycg_EA(1).json', 'PyCG E.A.(m)': 'pycg/pycg_EA(m).json',
             'JARVIS E.A.': 'jarvis/jarvis_EA.json'}
JARVIS_TYPES = {'str': '<str>', 'list': '<list>', 'dict': '<map>'}
PYCG_TYPES = {'PyStr': 'str', 'PyList': 'list', 'PyDict': 'dict', 'PySet': 'set',
              'PyTuple': 'tuple', 'PyBytes': 'bytes'}


# ---------------------------------------------------------------- scoring (gen_table.py)
def gen_table_score(truth: dict, cg: dict) -> dict:
    truth = {k: set(v) for k, v in truth.items()}
    cg = {k: set(v) for k, v in cg.items()}
    tp = sum(len(v & truth[k]) for k, v in cg.items() if k in truth)
    edges = sum(map(len, truth.values()))
    predicted = sum(map(len, cg.values()))
    fp, fn = predicted - tp, edges - tp
    return dict(tp=tp, fp=fp, fn=fn, edges=edges,
                precision=round(tp / (tp + fp), 4) if tp + fp else 0.0,
                recall=round(tp / edges, 4) if edges else 0.0)


def edge_diff(truth: dict, cg: dict) -> tuple[list, list]:
    t = {(a, b) for a, bs in truth.items() for b in bs}
    p = {(a, b) for a, bs in cg.items() for b in bs}
    return sorted(p - t), sorted(t - p)


# ---------------------------------------------------------------- KnitCode -> JARVIS notation
def jarvis_name(name: str, keep_library_calls: bool) -> str | None:
    """PyCG-notation external name -> JARVIS notation, None when it is a library call."""
    if name.startswith('<builtin>.'):
        return name
    if name.startswith('<**'):
        kind, _, method = name[3:].partition('**>.')
        base = PYCG_TYPES.get(kind, kind)
        return f"{JARVIS_TYPES.get(base, '<' + base + '>')}.{method}"
    return name if keep_library_calls else None


def _class_body_graph(graph: dict) -> dict:
    """Copy of graph whose module-level call sites inside a class body are owned by that class.

    JARVIS (like PyCG's scope model) names a class body as its own scope `mod.Cls`;
    KnitCode records the module that executes the class statement as the caller.
    Only the caller's name changes, never the target.
    """
    nodes = graph['nodes']
    by_file = {}
    for n in nodes:
        meta = n.get('navigation_metadata') or {}
        if n['kind'] in ('CLASS', 'FUNCTION', 'METHOD', 'LAMBDA') and meta.get('end_lineno'):
            by_file.setdefault(n['file'], []).append((n['line'], meta['end_lineno'], n))
    modules = {n['id'] for n in nodes if n['kind'] == 'MODULE'}

    def owner(file, line):
        inner = None
        for start, end, n in by_file.get(file, ()):
            if start <= line <= end and (inner is None or start >= inner[0]):
                inner = (start, end, n)
        return inner[2]['id'] if inner and inner[2]['kind'] == 'CLASS' else None

    def moved(edge):
        ev = edge.get('evidence') or {}
        if edge['source'] in modules and ev.get('file') and ev.get('line'):
            cls = owner(ev['file'], ev['line'])
            if cls:
                return {**edge, 'source': cls}
        return edge

    g = dict(graph)
    for key in ('edges', 'implicit_edges', 'supplemental_edges'):
        if key in graph:
            g[key] = [moved(e) for e in graph[key]]
    statuses = []
    for row in graph.get('call_statuses', []):
        if row.get('caller_id') in (None, *modules) and row.get('scope_context') == 'IN_CLASS_BODY':
            cls = owner(row['file'], row['line'])
            row = {**row, 'caller_id': cls} if cls else row
        statuses.append(row)
    g['call_statuses'] = statuses
    return g


def _import_pairs(symbols: dict, graph: dict) -> set:
    """Importing a project module executes it: importer scope -> imported module.

    `from pkg import sub` targets the submodule `pkg.sub`; `from mod import f`
    targets `mod`; `import a.b` targets `a.b`. Library modules are ignored.
    """
    modules = {n['canonical_name'] for n in graph['nodes'] if n['kind'] == 'MODULE'}
    pairs = set()
    for imp in symbols['imports']:
        # Longest project module that prefixes the resolved name (relative imports included).
        name = imp.get('imported_canonical') or imp.get('imported_module') or ''
        if imp.get('level'):
            package = imp['module'].split('.')
            if not imp['file'].endswith('__init__.py'):
                package = package[:-1]
            package = package[:len(package) - (imp['level'] - 1)] if imp['level'] > 1 else package
            tail = '.'.join(x for x in (imp.get('imported_module'), imp.get('imported_name')) if x)
            name = '.'.join([*package, tail]) if tail else '.'.join(package)
        parts = name.split('.')
        target = next(('.'.join(parts[:i]) for i in range(len(parts), 0, -1)
                       if '.'.join(parts[:i]) in modules), None)
        caller = imp['module'] if imp['scope'] == '<module>' else f"{imp['module']}.{pycg_scope(imp['scope'])}"
        if target and target != imp['module']:
            pairs.add((caller, target))
    return pairs


BUILTIN_DECORATORS = ('classmethod', 'staticmethod', 'property')


def _builtin_decorator_pairs(symbols: dict) -> set:
    """`@classmethod` etc. call the builtin while the enclosing scope runs.

    JARVIS's ground truth counts these (`mod.Cls -> <builtin>.classmethod`);
    PyCG's does not, so this is a JARVIS-only convention. A name shadowed by a
    project definition or import in the same module is not the builtin.
    """
    shadowed = {(s['module'], s['name']) for s in symbols['symbols'] if s.get('scope') == '<module>'}
    shadowed |= {(i['module'], i['local_name']) for i in symbols['imports']}
    pairs = set()
    for s in symbols['symbols']:
        for decorator in s.get('decorators') or []:
            if decorator in BUILTIN_DECORATORS and (s['module'], decorator) not in shadowed:
                scope = s.get('scope') or '<module>'
                caller = s['module'] if scope == '<module>' else f"{s['module']}.{pycg_scope(scope)}"
                pairs.add((caller, '<builtin>.' + decorator))
    return pairs


def _class_definition_pairs(symbols: dict) -> set:
    """Executing a class statement runs its body: enclosing scope -> class.

    JARVIS's macro ground truth has this edge for every class (as do the
    PyCG and JARVIS outputs); its micro ground truth, inherited from PyCG,
    does not, so this is a macro-only convention like 'imports'.
    """
    pairs = set()
    for s in symbols['symbols']:
        if s['kind'] == 'CLASS':
            scope = s.get('scope') or '<module>'
            caller = s['module'] if scope == '<module>' else f"{s['module']}.{pycg_scope(scope)}"
            pairs.add((caller, pycg_scope(s['canonical_name'])))
    return pairs


MICRO_CONVENTIONS = ('class_body', 'builtin_decorators')
MACRO_CONVENTIONS = ('class_body', 'imports', 'builtin_decorators', 'class_definition')


def knitcode_cg(symbols: dict, graph: dict, keep_library_calls=False, conventions=()) -> dict:
    """KnitCode call graph in JARVIS notation.

    conventions=():          builtin notation only (raw).
    'class_body' / 'imports' / 'builtin_decorators': the JARVIS conventions above.
    None of them consults the ground truth. The artifact's micro ground truth (inherited from PyCG) has no
    module import edges while its macro ground truth has them, so 'imports' is used
    for macro only.
    """
    if 'class_body' in conventions:
        graph = _class_body_graph(graph)
    internal, external, _ = to_pycg(symbols, graph, include_implicit=True)
    pairs = set(internal)
    for caller, target in external:
        mapped = jarvis_name(target, keep_library_calls)
        if mapped:
            pairs.add((caller, mapped))
    if 'imports' in conventions:
        pairs |= _import_pairs(symbols, graph)
    if 'builtin_decorators' in conventions:
        pairs |= _builtin_decorator_pairs(symbols)
    if 'class_definition' in conventions:
        pairs |= _class_definition_pairs(symbols)
    return adjacency(pairs)


def analyze(root: Path):
    from ast_parser import scan_repository
    from symbol_builder import build_symbol_result
    from graph_builder import build_graph
    from unresolved_classifier import reclassify_graph
    from call_status import annotate_call_statuses
    facts = scan_repository(root, source_roots=['.'])
    symbols = build_symbol_result(facts)
    graph = annotate_call_statuses(reclassify_graph(build_graph(symbols), symbols), symbols)
    return facts, symbols, graph


def peak_rss_mb() -> float | None:
    try:
        import resource
    except ImportError:  # Windows: no stdlib equivalent
        return None
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(rss / (1024 * 1024 if sys.platform == 'darwin' else 1024), 1)


# ---------------------------------------------------------------- micro
def run_micro(jarvis: Path, keep_library_calls: bool) -> dict:
    norm = lambda s: s.replace(' ', '_')  # dataset "new_direct calls" vs ground truth "new_direct_calls"
    truths = {(norm(p.parent.parent.name), p.parent.name): p
              for p in (jarvis / 'ground_truth/micro_benchmark').glob('*/*/callgraph.json')}
    records = []
    for case in sorted(p for p in (jarvis / 'dataset/micro_benchmark').glob('*/*') if p.is_dir()):
        key = (norm(case.parent.name), case.name)
        if key not in truths:
            continue
        start = time.perf_counter()
        with contextlib.redirect_stdout(io.StringIO()):
            _, symbols, graph = analyze(case)
        cg = knitcode_cg(symbols, graph, keep_library_calls, MICRO_CONVENTIONS)
        truth = json.loads(truths[key].read_text())
        raw = gen_table_score(truth, knitcode_cg(symbols, graph, keep_library_calls))
        s = gen_table_score(truth, cg)
        fps, fns = edge_diff(truth, cg)
        records.append(dict(category=key[0], case=key[1], **s, complete=int(s['fp'] == 0),
                            sound=int(s['fn'] == 0), raw_tp=raw['tp'], raw_fp=raw['fp'], raw_fn=raw['fn'],
                            false_positives=fps, false_negatives=fns,
                            seconds=round(time.perf_counter() - start, 4)))
    cats = defaultdict(lambda: defaultdict(int))
    for r in records:
        c = cats[r['category']]
        c['cases'] += 1
        for k in ('complete', 'sound', 'tp', 'fp', 'fn', 'edges'):
            c[k] += r[k]
    total = {k: sum(c[k] for c in cats.values()) for k in ('cases', 'complete', 'sound', 'tp', 'fp', 'fn', 'edges')}
    total['precision'] = round(total['tp'] / (total['tp'] + total['fp']), 4)
    total['recall'] = round(total['tp'] / total['edges'], 4)
    total['raw'] = {k: sum(r['raw_' + k] for r in records) for k in ('tp', 'fp', 'fn')}
    return dict(total=total, categories={k: dict(v) for k, v in sorted(cats.items())}, records=records)


def print_micro(result: dict) -> None:
    print(f"{'category':20}{'C.':>8}{'S.':>8}{'TP':>10}{'FP':>10}{'FN':>10}")
    for name, c in result['categories'].items():
        n, e = c['cases'], c['edges']
        print(f"{name:20}{c['complete']:>4}/{n:<3}{c['sound']:>4}/{n:<3}"
              f"{c['tp']:>6}/{e:<3}{c['fp']:>6}/{e:<3}{c['fn']:>6}/{e:<3}")
    t = result['total']
    print(f"{'total':20}{t['complete']:>4}/{t['cases']:<3}{t['sound']:>4}/{t['cases']:<3}"
          f"{t['tp']:>6}/{t['edges']:<3}{t['fp']:>6}/{t['edges']:<3}{t['fn']:>6}/{t['edges']:<3}")
    print(f"precision {t['precision']:.2%}  recall {t['recall']:.2%}   (raw notation only: {t['raw']})")


# ---------------------------------------------------------------- macro
def macro_one(jarvis: Path, project: str, out: Path, keep_library_calls: bool) -> dict:
    """Analyze one project in this process (called in a fresh subprocess for clean time/memory)."""
    gt_dir, package_rel, patterns = MACRO[project]
    package = jarvis / 'dataset/macro_benchmark/pj' / package_rel
    files = sorted({p for pat in patterns for p in package.glob(pat)})
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for path in files:
            dest = root / path.relative_to(package)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
        start = time.perf_counter()
        with contextlib.redirect_stdout(io.StringIO()):
            facts, symbols, graph = analyze(root)
        cg = knitcode_cg(symbols, graph, keep_library_calls, MACRO_CONVENTIONS)
        seconds = time.perf_counter() - start
        cg_raw = knitcode_cg(symbols, graph, keep_library_calls)
    truth = json.loads((jarvis / 'ground_truth/macro_benchmark' / gt_dir / 'EA.json').read_text())
    fps, fns = edge_diff(truth, cg)
    (out / 'knitcode_EA.json').write_text(json.dumps(cg, indent=2) + '\n', encoding='utf-8')
    result = dict(project=project, files=len(files), parse_errors=len(facts['parse_errors']),
                  lines=sum(len(p.read_text(encoding='utf-8', errors='replace').splitlines()) for p in files),
                  seconds=round(seconds, 2), peak_rss_mb=peak_rss_mb(),
                  knitcode_raw=gen_table_score(truth, cg_raw),
                  knitcode=gen_table_score(truth, cg), false_positives=fps, false_negatives=fns)
    ref_dir = jarvis / 'reproducing_RQ2/macro_benchmark'
    ref_dir = next((d for d in ref_dir.iterdir() if d.name.lower() == project.lower()), None)
    for label, rel in REFERENCE.items():
        path = ref_dir / rel if ref_dir else None
        if path and path.exists():
            result[label] = gen_table_score(truth, json.loads(path.read_text()))
    (out / 'result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return result


def run_macro(jarvis: Path, out: Path, keep_library_calls: bool) -> list[dict]:
    results = []
    for project in MACRO:
        cmd = [sys.executable, __file__, '_macro_one', '--jarvis', str(jarvis),
               '--output', str(out / project), '--project', project]
        if keep_library_calls:
            cmd.append('--keep-library-calls')
        if ENGINE_ROOT:
            cmd += ['--engine-root', str(ENGINE_ROOT.resolve())]
        subprocess.run(cmd, check=True)
        results.append(json.loads((out / project / 'result.json').read_text(encoding='utf-8')))
    labels = ['knitcode_raw', 'knitcode', *REFERENCE]
    summary = dict(projects=results, average={
        label: dict(precision=round(sum(r[label]['precision'] for r in results if label in r) / len(results), 4),
                    recall=round(sum(r[label]['recall'] for r in results if label in r) / len(results), 4))
        for label in labels})
    (out / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return results


def print_macro(results: list[dict]) -> None:
    labels = ['knitcode_raw', 'knitcode', *REFERENCE]
    print(f"{'project':13}{'lines':>7}" + ''.join(f'{l:>22}' for l in labels) + f"{'time(s)':>9}{'RSS(MB)':>9}")
    for r in results:
        cells = ''.join(f"{r[l]['precision']:>10.2f} / {r[l]['recall']:<9.2f}" if l in r else f"{'-':>22}"
                        for l in labels)
        print(f"{r['project']:13}{r['lines']:>7}{cells}{r['seconds']:>9}{r['peak_rss_mb'] or '-':>9}")
    avg = ''.join(f"{sum(r[l]['precision'] for r in results) / len(results):>10.2f} / "
                  f"{sum(r[l]['recall'] for r in results) / len(results):<9.2f}" for l in labels)
    print(f"{'average':20}{avg}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('mode', choices=('micro', 'macro', '_macro_one'))
    parser.add_argument('--jarvis', type=Path, required=True, help='the artifact\'s Jarvis/ directory')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--project', choices=tuple(MACRO))
    parser.add_argument('--keep-library-calls', action='store_true')
    parser.add_argument('--engine-root', type=Path, help='engine checkout to score (default: this one)')
    args = parser.parse_args(argv)
    jarvis = args.jarvis.resolve()
    if args.mode == 'micro':
        result = run_micro(jarvis, args.keep_library_calls)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        print_micro(result)
    elif args.mode == 'macro':
        print_macro(run_macro(jarvis, args.output.resolve(), args.keep_library_calls))
    else:
        macro_one(jarvis, args.project, args.output, args.keep_library_calls)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

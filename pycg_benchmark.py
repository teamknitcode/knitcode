"""PyCG macro-benchmark: KnitCode vs. the hand-made ground truth (and PyCG).

The five projects, their ground-truth call graphs and the scoring functions come
from the PyCG artifact (https://github.com/vitsalis/pycg-evaluation, ICSE'21).
Inputs follow scripts/generate_pycg_cgs.sh exactly: the same files and the same
`--package` root, so module names match the ground truth.

Usage:
    python pycg_benchmark.py --benchmark ../pycg-evaluation --output out/pycg
    python pycg_benchmark.py --benchmark ../pycg-evaluation --pycg-python PY39
    python pycg_benchmark.py --benchmark ../pycg-evaluation --pycg-cgs DIR

Scores (unique caller -> callee pairs, function-level, PyCG notation):
  paper      all selected explicit + implicit + grounded external calls (headline score)
  internal   project functions only (KnitCode CALLS edges)
  full       internal + external calls with static provenance
             (KNOWN_NON_INTERNAL call sites: builtins, stdlib, imports)
precision/recall use the artifact's own measure_precision/measure_recall.
PyCG itself is run with --pycg-python (an interpreter with PyCG installed;
the 2021 artifact version needs Python <= 3.9) or read from --pycg-cgs, and
the overlap of the two tools is reported as well.
No ground-truth-driven renaming, suffix matching or edge deletion is done.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import runpy
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL_DIR))
from main import run  # noqa: E402

from pycg_adapter import (PROJECTS, LAYOUT, BUILTIN_TYPES, DOTTED, select_files, pycg_scope,
                          pycg_external, to_pycg, adjacency, score, overlap)


def run_pycg(python: str, package: Path, files: list[Path], dest: Path) -> float:
    """Run PyCG like generate_pycg_cgs.sh; returns seconds."""
    start = time.perf_counter()
    result = subprocess.run([python, '-m', 'pycg', '--package', str(package), *map(str, files)],
                            capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if result.returncode:
        raise RuntimeError(f'PyCG failed for {package}:\n{result.stderr[-2000:]}')
    # PyCG builds module names by replacing "/" in relative paths
    # (utils/common.py: to_mod_name), so on Windows a nested module comes out
    # as "pkg\\mod.func". Backslashes never occur in Python names.
    graph = {caller.replace('\\', '.'): [callee.replace('\\', '.') for callee in callees]
             for caller, callees in json.loads(result.stdout).items()}
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(graph, indent=2) + '\n', encoding='utf-8')
    return time.perf_counter() - start


def evaluate(benchmark: Path, project: str, out: Path, scorer: dict, pycg_cgs: Path | None,
             pycg_python: str | None = None, analysis_profile=None, call_policy=None) -> dict:
    source = benchmark / 'data/macro-benchmark/projects' / project
    package, files = select_files(source, project)
    truth = json.loads((benchmark / 'data/macro-benchmark/ground-truth-cgs' / (project + '.json')).read_text())
    out.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp, \
            (out / 'analysis.log').open('w', encoding='utf-8') as log, contextlib.redirect_stdout(log):
        root = Path(tmp)
        for path in files:
            dest = root / path.resolve().relative_to(package)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
        facts, symbols, graph = run(root, out / 'analysis', source_roots=['.'],
                                   analysis_profile=analysis_profile, call_policy=call_policy)
    seconds = time.perf_counter() - start
    internal, external, skipped = to_pycg(symbols, graph)
    full = internal | external
    implicit_internal, _, _ = to_pycg(symbols, graph, include_implicit=True)
    full_with_implicit = full | implicit_internal
    primary_internal, primary_external, _ = to_pycg(symbols, graph, include_supplemental=False)
    primary_full = primary_internal | primary_external
    (out / 'knitcode_cg.json').write_text(json.dumps(adjacency(full), indent=2) + '\n', encoding='utf-8')
    (out / 'knitcode_with_implicit_cg.json').write_text(
        json.dumps(adjacency(full_with_implicit), indent=2) + '\n', encoding='utf-8')
    result = {'project': project, 'files': len(files), 'parse_errors': len(facts['parse_errors']),
              'seconds': round(seconds, 2), 'skipped': skipped,
              'internal': score(internal, truth, scorer), 'full': score(full, truth, scorer),
              'full_with_implicit': score(full_with_implicit, truth, scorer),
              'paper': score(full_with_implicit, truth, scorer),
              'primary_full': score(primary_full, truth, scorer),
              'analysis_profile': graph.get('analysis_profile'),
              'call_graph_policy': graph.get('call_graph_policy'),
              'supplemental_summary': graph.get('supplemental_summary')}
    pycg_path = pycg_cgs / (project + '.json') if pycg_cgs else None
    if pycg_python:
        pycg_path = out / 'pycg_cg.json'
        result['pycg_seconds'] = round(run_pycg(pycg_python, package, files, pycg_path), 2)
    if pycg_path and pycg_path.exists():
        pycg = json.loads(pycg_path.read_text())
        pycg_pairs = {(a, b) for a, bs in pycg.items() for b in bs}
        result['pycg'] = score(pycg_pairs, truth, scorer)
        result['overlap_with_pycg'] = overlap(full_with_implicit, pycg_pairs, truth)
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def print_table(results: list[dict]) -> None:
    def pct(x):
        return f'{x * 100:.1f}%'
    print('\n| project | KnitCode explicit internal P / R | KnitCode all calls P / R (F1) | PyCG P / R (F1) | overlap (Jaccard) |')
    print('|---|---|---|---|---|')
    for r in results:
        i, f, p, o = r['internal'], r['paper'], r.get('pycg'), r.get('overlap_with_pycg')
        print(f"| {r['project']} | {pct(i['precision'])} / {pct(i['recall'])} | "
              f"{pct(f['precision'])} / {pct(f['recall'])} ({pct(f['f1'])}) | "
              + (f"{pct(p['precision'])} / {pct(p['recall'])} ({pct(p['f1'])}) | " if p else '- | ')
              + (f"both {o['both']}, KnitCode only {o['only_knitcode']}, PyCG only {o['only_pycg']} "
                 f"({pct(o['jaccard'])}) |" if o else '- |'))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--benchmark', type=Path, required=True,
                        help='pycg-evaluation checkout (with data/macro-benchmark submodules)')
    parser.add_argument('--output', type=Path, default=Path('out/pycg'))
    parser.add_argument('--pycg-cgs', type=Path, help='directory of PyCG outputs <project>.json (optional)')
    parser.add_argument('--pycg-python', help='Python interpreter with PyCG installed; runs PyCG (optional)')
    parser.add_argument('--project', choices=PROJECTS, action='append')
    parser.add_argument('--analysis-profile', choices=('baseline', 'integrated'), default=None)
    parser.add_argument('--call-policy', choices=('primary', 'augmented', 'supported'), default=None)
    args = parser.parse_args(argv)
    scorer = runpy.run_path(str(args.benchmark / 'scripts/compare_macro_benchmark_cg.py'))
    results = []
    for project in args.project or PROJECTS:
        results.append(evaluate(args.benchmark, project, args.output / project, scorer,
                                args.pycg_cgs, args.pycg_python, args.analysis_profile, args.call_policy))
        print(f"{project}: done in {results[-1]['seconds']}s", flush=True)
    (args.output / 'summary.json').write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    print_table(results)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

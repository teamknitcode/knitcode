"""Pure PyCG representation/scoring adapter, independent of any analysis engine."""
from __future__ import annotations
from collections import defaultdict
from pathlib import Path
import re

PROJECTS = ('Sublist3r', 'asciinema', 'autojump', 'fabric', 'face_classification')
# project -> (--package root, directory whose .py files are analyzed), as in
# generate_pycg_cgs.sh. fabric also drops paths containing "tests"/"setup.py".
LAYOUT = {'autojump': ('bin', 'bin'), 'fabric': ('.', '.'), 'asciinema': ('.', 'asciinema'),
          'face_classification': ('src', 'src'), 'Sublist3r': ('.', '.')}
# PyCG notation for methods of builtin types.
BUILTIN_TYPES = {'str': 'PyStr', 'bytes': 'PyBytes', 'list': 'PyList', 'dict': 'PyDict',
                 'set': 'PySet', 'tuple': 'PyTuple'}
# An external target must be a dotted name. Descriptive origins such as
# "Manager().dict" or "a.join or b.join" name no single function.
DOTTED = re.compile(r'[A-Za-z_]\w*(\.\w+)*')


def pycg_scope(name: str) -> str:
    """PyCG uses lexical scopes without CPython's non-identifier <locals> marker."""
    return name.replace('.<locals>.', '.')


def select_files(project_dir: Path, project: str) -> tuple[Path, list[Path]]:
    package, scope = LAYOUT[project]
    files = sorted((project_dir / scope).rglob('*.py'))
    if project == 'fabric':
        files = [p for p in files if 'tests' not in p.relative_to(project_dir).as_posix()
                 and 'setup.py' not in p.relative_to(project_dir).as_posix()]
    return (project_dir / package).resolve(), files


def pycg_external(name: str) -> str:
    if name.startswith('builtins.'):
        return '<builtin>.' + name[len('builtins.'):]
    head, dot, rest = name.partition('.')
    if dot and head in BUILTIN_TYPES:
        return f'<**{BUILTIN_TYPES[head]}**>.{rest}'
    return name


def to_pycg(symbols: dict, graph: dict, *, include_implicit=False, include_supplemental=None) -> tuple[set, set, dict]:
    """(internal pairs, external pairs, skipped counts) in PyCG's notation."""
    if include_supplemental is None:
        include_supplemental = graph.get('call_graph_policy') in ('augmented', 'supported')
    nodes = {n['id']: n for n in [*graph['nodes'], *graph.get('supplemental_nodes', [])]}
    # PyCG numbers lambdas per enclosing scope: scope.<lambda1>, <lambda2>, ...
    lambdas, counters = {}, defaultdict(int)
    for s in sorted((s for s in symbols['symbols'] if s['kind'] == 'LAMBDA'),
                    key=lambda s: (s['file'], s['line'], s.get('column', 0))):
        scope = pycg_scope(s['canonical_name']).rsplit('.', 1)[0]
        counters[scope] += 1
        lambdas[s['canonical_name']] = f'{scope}.<lambda{counters[scope]}>'

    def name(node_id):
        canonical = nodes[node_id]['canonical_name']
        return lambdas.get(canonical, pycg_scope(canonical))

    # PyCG's nodes are functions: `Cls()` is a call to Cls.__init__ (a CALLS
    # edge here). A class without a project __init__ runs no project function
    # body, so INSTANTIATES edges are not pairs; they are counted instead.
    internal, skipped = set(), {'class_instantiation_without_init': 0, 'non_dotted_external': 0}
    init_sites = {e['evidence'].get('call_id') for e in graph['edges']
                  if e['type'] == 'CALLS' and nodes[e['target']]['name'] == '__init__'}
    edges = [*graph['edges'], *(graph.get('implicit_edges', []) if include_implicit else [])]
    if include_supplemental:
        from ljy_integration import selected_supplemental_edges
        edges += [e for e in selected_supplemental_edges(graph)
                  if include_implicit or e['type'] != 'CALLS_IMPLICIT']
    for e in edges:
        if e['type'] == 'INSTANTIATES':
            skipped['class_instantiation_without_init'] += e['evidence'].get('call_id') not in init_sites
        elif e['type'] in ('CALLS', 'CALLS_IMPLICIT', 'CALLS_OVERRIDE'):
            internal.add((name(e['source']), name(e['target'])))

    module_of = {f: n['canonical_name'] for n in graph['nodes'] if n['kind'] == 'MODULE' for f in [n['file']]}
    external = set()
    for row in graph.get('call_statuses', []):
        target = (row.get('evidence') or {}).get('origin_name')
        if row['status'] != 'KNOWN_NON_INTERNAL' or not target:
            continue
        if not DOTTED.fullmatch(target):
            skipped['non_dotted_external'] += 1
            continue
        caller = name(row['caller_id']) if row.get('caller_id') in nodes else module_of.get(row['file'])
        if caller:
            external.add((caller, pycg_external(target)))
    return internal, external, skipped


def adjacency(pairs) -> dict:
    result = defaultdict(set)
    for a, b in pairs:
        result[a].add(b)
    return {a: sorted(bs) for a, bs in sorted(result.items())}


def score(pairs, truth: dict, scorer: dict) -> dict:
    actual = adjacency(pairs)
    expected = {(a, b) for a, bs in truth.items() for b in bs}
    precision = scorer['measure_precision'](actual, truth)
    recall = scorer['measure_recall'](actual, truth)
    return {'precision': precision, 'recall': recall,
            'f1': 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            'tp': len(pairs & expected), 'fp': len(pairs - expected), 'fn': len(expected - pairs)}


def overlap(knit: set, pycg: set, truth: dict) -> dict:
    expected = {(a, b) for a, bs in truth.items() for b in bs}
    both, only_knit, only_pycg = knit & pycg, knit - pycg, pycg - knit
    return {'both': len(both), 'only_knitcode': len(only_knit), 'only_pycg': len(only_pycg),
            'jaccard': len(both) / len(knit | pycg) if knit | pycg else 0.0,
            'both_correct': len(both & expected),
            'only_knitcode_correct': len(only_knit & expected),
            'only_pycg_correct': len(only_pycg & expected)}



"""Evaluate the official 112 micro cases without executing their source."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import runpy
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pycg_adapter import to_pycg, adjacency, pycg_scope
import pycg_adapter
# A pure, common adapter can score an archived engine without importing the
# current engine's runtime. Each version runs in its own process.
engine_parser = argparse.ArgumentParser(add_help=False)
engine_parser.add_argument('--engine-root', type=Path)
engine_args, _ = engine_parser.parse_known_args()
if engine_args.engine_root:
    sys.path.insert(0, str(engine_args.engine_root.resolve()))
from ast_parser import scan_repository
from symbol_builder import build_symbol_result
from graph_builder import build_graph
from unresolved_classifier import reclassify_graph
from call_status import annotate_call_statuses


def evaluate(benchmark, include_implicit=True, analysis_profile=None, call_policy=None):
    official = runpy.run_path(str(benchmark / 'scripts/micro_benchmark.py'))
    records = []
    for truth_path in sorted((benchmark / 'data/micro-benchmark').glob('*/*/callgraph.json')):
        root = truth_path.parent
        start = time.perf_counter()
        facts = scan_repository(root, source_roots=['.'])
        symbols = build_symbol_result(facts)
        graph = annotate_call_statuses(reclassify_graph(
            build_graph(symbols, profile=analysis_profile, call_policy=call_policy), symbols), symbols)
        internal, external, skipped = to_pycg(symbols, graph, include_implicit=include_implicit)
        pairs = internal | external
        actual = adjacency(pairs)
        for _, target in pairs:
            actual.setdefault(target, [])
        lambdas, counters = {}, defaultdict(int)
        for symbol in sorted((s for s in symbols['symbols'] if s['kind'] == 'LAMBDA'),
                             key=lambda s: (s['file'], s['line'], s.get('column', 0))):
            scope = pycg_scope(symbol['canonical_name']).rsplit('.', 1)[0]
            counters[scope] += 1
            lambdas[symbol['canonical_name']] = f'{scope}.<lambda{counters[scope]}>'
        # Official soundness also requires nodes with zero outgoing edges.
        # Include engine-discovered scopes, never nodes supplied by the oracle.
        for node in graph['nodes']:
            if node['kind'] in ('MODULE', 'FUNCTION', 'METHOD', 'LAMBDA'):
                name = node['canonical_name']
                actual.setdefault(lambdas.get(name, pycg_scope(name)), [])
        truth = json.loads(truth_path.read_text())
        expected = {(a, b) for a, bs in truth.items() for b in bs}
        records.append(dict(case=root.relative_to(benchmark / 'data/micro-benchmark').as_posix(),
                            category=root.parent.name,
                            complete=official['equal_complete'](actual, truth),
                            sound=official['equal_sound'](actual, truth),
                            strict_no_extra_edges=not bool(pairs - expected),
                            all_truth_edges_found=not bool(expected - pairs),
                            tp=len(pairs & expected), fp=len(pairs - expected), fn=len(expected - pairs),
                            false_positives=sorted(pairs - expected),
                            false_negatives=sorted(expected - pairs),
                            missing_nodes=sorted(set(truth) - set(actual)),
                            parse_errors=facts['parse_errors'], skipped=skipped,
                            seconds=time.perf_counter() - start))
    categories = defaultdict(lambda: dict(cases=0, complete=0, sound=0, strict_no_extra_edges=0,
                                         all_truth_edges_found=0))
    for row in records:
        cat = categories[row['category']]
        cat['cases'] += 1
        for key in ('complete', 'sound', 'strict_no_extra_edges', 'all_truth_edges_found'):
            cat[key] += row[key]
    import graph_builder
    return dict(engine_module=str(Path(graph_builder.__file__).resolve()),
                adapter_module=str(Path(pycg_adapter.__file__).resolve()),
                include_implicit=include_implicit, cases=len(records), complete=sum(r['complete'] for r in records),
                sound=sum(r['sound'] for r in records), categories=dict(categories), records=records)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmark', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--include-implicit', action='store_true', default=True)
    parser.add_argument('--no-implicit', action='store_false', dest='include_implicit',
                        help='Explicit-only diagnostic; default evaluation includes implicit calls')
    parser.add_argument('--analysis-profile', choices=('baseline', 'integrated'), default=None)
    parser.add_argument('--engine-root', type=Path, help='Archived engine; scores use the current pure adapter')
    parser.add_argument('--call-policy', choices=('primary', 'augmented', 'supported'), default=None)
    args = parser.parse_args()
    result = evaluate(args.benchmark.resolve(), args.include_implicit, args.analysis_profile, args.call_policy)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'records'}, indent=2))

"""Apply the current, common PyCG name adapter to saved predictions (no engine rerun)."""
import argparse
import json
from pathlib import Path
import runpy
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pycg_adapter import PROJECTS, to_pycg, score, adjacency


def rescore(source, benchmark, output):
    scorer = runpy.run_path(str(benchmark / 'scripts/compare_macro_benchmark_cg.py'))
    rows = []
    for project in PROJECTS:
        folder = source / project / 'analysis'
        symbols = json.loads((folder/'symbol_result.json').read_text())
        graph = json.loads((folder/'graph_result.json').read_text())
        truth = json.loads((benchmark/'data/macro-benchmark/ground-truth-cgs'/f'{project}.json').read_text())
        explicit, external, _ = to_pycg(symbols, graph, include_implicit=False)
        internal, external, skipped = to_pycg(symbols, graph, include_implicit=True)
        output.mkdir(parents=True, exist_ok=True)
        (output/f'{project}-calls.json').write_text(json.dumps(adjacency(internal | external), indent=2)+'\n')
        rows.append(dict(project=project, paper=score(internal | external, truth, scorer),
                         explicit_only=score(explicit | external, truth, scorer), skipped=skipped,
                         note='Re-scored frozen predictions with common scope names; no new engine inference'))
    (output/'summary.json').write_text(json.dumps(rows, indent=2)+'\n')
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--benchmark', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(rescore(args.source, args.benchmark, args.output), indent=2))

"""Re-score published Jarvis EA predictions on the recorded source-function scope."""
import argparse
import hashlib
import json
from pathlib import Path

from evaluate import score


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--results', type=Path, default=Path(__file__).parent / 'results')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    ours = {r['project']: r for r in json.loads((args.results / 'results.json').read_text())}
    output = []
    for project in ('sqlparse', 'furl'):
        vocabulary = set(json.loads((args.results / project / 'function_vocabulary.json').read_text()))
        truth = json.loads((args.results / project / 'truth_projected.json').read_text())
        truth = {(a, b) for a, bs in truth.items() for b in bs}
        relative = Path('Jarvis/reproducing_RQ2/macro_benchmark') / project / 'jarvis/jarvis_EA.json'
        file = args.artifact / relative
        raw = json.loads(file.read_text())
        raw = {(a, b) for a, bs in raw.items() for b in bs}
        projected = {(a, b) for a, b in raw if a in vocabulary and b in vocabulary}
        measured = dict(score(projected, truth), raw_pairs=len(raw), projected_pairs=len(projected),
                        source_sha256=hashlib.sha256(file.read_bytes()).hexdigest(),
                        source_path=relative.as_posix())
        output.append(dict(project=project, jarvis_published_EA=measured,
                           knitcode_static=ours[project]['static'],
                           knitcode_hybrid=ours[project]['modes']['calls-only']['score']))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + '\n')


if __name__ == '__main__':
    main()

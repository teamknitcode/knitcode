"""Re-score PR #5 (experiments/2026-11-16-jarvis) with a given static engine.

Usage: python hybrid_recompute.py <engine checkout> <checkout containing PR #5 results> <pythonJaRvis.github.io>
Static edges are projected on source-declared app functions exactly as PR #5 evaluate.py does;
the saved observed-calls-only.json (macOS run) is reused, the target tests are not executed.
"""
import sys, json, tempfile, shutil, contextlib, io
from pathlib import Path
engine, pr5, jarvis = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
sys.path.insert(0, str(engine)); sys.path.insert(0, str(pr5 / 'experiments/2026-11-16-jarvis'))
from evaluate import source_functions, score
from main import run
from pycg_adapter import to_pycg
for project in ('sqlparse', 'furl'):
    original = jarvis / 'Jarvis/dataset/macro_benchmark/pj' / project
    files = sorted((original / project).rglob('*.py'))
    vocab = source_functions(files, original)
    res = pr5 / 'experiments/2026-11-16-jarvis/results' / project
    truth = {(a, b) for a, bs in json.loads((res / 'truth_projected.json').read_text()).items() for b in bs}
    with tempfile.TemporaryDirectory() as t:
        src = Path(t) / 'sources'
        for f in files:
            d = src / f.relative_to(original); d.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(f, d)
        with contextlib.redirect_stdout(io.StringIO()):
            facts, symbols, graph = run(src, Path(t) / 'static', source_roots=['.'])
    i, e, _ = to_pycg(symbols, graph, include_implicit=True)
    static = {(a, b) for a, b in i | e if a in vocab and b in vocab}
    old_static = {(a, b) for a, bs in json.loads((res / 'static_projected.json').read_text()).items() for b in bs}
    observed = {(a, b) for a, bs in json.loads((res / 'observed-calls-only.json').read_text()).items() for b in bs}
    f = lambda s: 'P %.2f%% R %.2f%% F1 %.2f%% (TP %d FP %d FN %d)' % (s['precision']*100, s['recall']*100, s['f1']*100, s['tp'], s['fp'], s['fn'])
    print(project, 'truth', len(truth))
    print('  PR5 static (main engine)   ', f(score(old_static, truth)))
    print('  PR5 static+calls (main)    ', f(score(old_static | observed, truth)))
    print('  my static                  ', f(score(static, truth)))
    print('  my static+calls            ', f(score(static | observed, truth)))
    print('  my static new vs old: +%d -%d ; observed already in my static: %d/%d' % (len(static - old_static), len(old_static - static), len(observed & static), len(observed)))

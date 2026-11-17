"""Fixed-workload macro ground-truth study; no truth-directed edge filtering.

Only source-verified mapped project calls are added. External observations
are retained in trace files but not converted without a canonical adapter.
"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import runpy
import shutil
import statistics
import subprocess
import sys
import time

WORKLOADS = {
    'autojump': ['tests/unit'],
    'asciinema': ['tests/config_test.py', 'tests/asciicast'],
    # connection.py had two failures in baseline preflight; exclude the whole
    # module before scoring, rather than masking failed trace execution.
    'fabric': ['tests/transfer.py', 'tests/group.py', 'tests/config.py'],
}


def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--tool', type=Path, required=True)
    p.add_argument('--benchmark', type=Path, required=True)
    p.add_argument('--python', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--projects', nargs='+', choices=WORKLOADS, default=list(WORKLOADS))
    p.add_argument('--rounds', type=int, default=3)
    p.add_argument('--legacy-pytest', action='store_true', help='Use original relaxed plugin with plain assertions')
    args = p.parse_args()
    tool, bench, out = args.tool.resolve(), args.benchmark.resolve(), args.out.resolve()
    python = args.python.absolute()
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(tool))
    from main import run
    from pycg_adapter import select_files, to_pycg, pycg_scope, adjacency, score
    scorer = runpy.run_path(str(bench / 'scripts/compare_macro_benchmark_cg.py'))
    def grade(pairs, truth):
        official = score(pairs, truth, scorer)
        tp, fp, fn = (official[k] for k in ('tp', 'fp', 'fn'))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        return dict(official=official, precision=precision, recall=recall,
                    f1=2 * precision * recall / (precision + recall) if precision + recall else 0.0,
                    tp=tp, fp=fp, fn=fn)
    metadata = {
        'platform': platform.platform(), 'rounds': args.rounds,
        'python': subprocess.check_output([str(python), '--version'], text=True).strip(),
        'benchmark_commit': subprocess.check_output(['git', '-C', str(bench), 'rev-parse', 'HEAD'], text=True).strip(),
        'tool_commit': subprocess.check_output(['git', '-C', str(tool), 'rev-parse', 'HEAD'], text=True).strip(),
        'tool_source_sha256': {str(f.relative_to(tool)): hashlib.sha256(f.read_bytes()).hexdigest()
                               for f in [tool / 'dynamic_analysis.py', *sorted((tool / 'runtime_validation').glob('*.py'))]},
        'dependencies': subprocess.check_output([str(python), '-m', 'pip', 'freeze'], text=True).splitlines(),
        'workloads': {k: WORKLOADS[k] for k in args.projects},
        'legacy_pytest': args.legacy_pytest,
        'policy': 'static paper union all source-verified mapped runtime project function targets; no truth filtering',
    }
    save(out / 'metadata.json', metadata)
    results = []
    for project in args.projects:
        original = bench / 'data/macro-benchmark/projects' / project
        dest = out / project
        dest.mkdir(exist_ok=True)
        package, files = select_files(original, project)
        sources = dest / 'sources'
        sources.mkdir(exist_ok=True)
        for source in files:
            target = sources / source.relative_to(package)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        started = time.perf_counter()
        with (dest / 'static.log').open('w') as log, contextlib.redirect_stdout(log):
            facts, symbols, graph = run(sources, dest / 'static', source_roots=['.'])
        static_seconds = time.perf_counter() - started
        internal, external, _ = to_pycg(symbols, graph, include_implicit=True)
        static = internal | external
        nodes = {n['id']: n for n in graph['nodes']}
        truth_path = bench / 'data/macro-benchmark/ground-truth-cgs' / f'{project}.json'
        truth = json.loads(truth_path.read_text())
        truth_pairs = {(a, b) for a, bs in truth.items() for b in bs}
        env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
                   PYTHONPATH=os.pathsep.join([str(original), str(package), str(original / 'tests')]))
        tests = ['-q', '-o', 'addopts=', *WORKLOADS[project]]
        if project == 'fabric':
            tests = ['-p', 'pytest_relaxed.plugin', *tests]
        if args.legacy_pytest:
            tests = ['--assert=plain', *tests]
        rows = []
        for repeat in range(args.rounds):
            modes = ['baseline', 'calls-only', 'full']
            for mode in modes[repeat % 3:] + modes[:repeat % 3]:
                trace = dest / f'{mode}-{repeat}.json'
                if mode == 'baseline':
                    command = [str(python), '-m', 'pytest', *tests]
                else:
                    command = [str(python), str(tool / 'dynamic_analysis.py'), 'record', str(package),
                               '--module', 'pytest', '--cwd', str(original), '--source-root', '.',
                               '--python', str(python), '--out', str(trace)]
                    if mode == 'calls-only':
                        command += ['--calls-only']
                    command += ['--', *tests]
                start = time.perf_counter()
                execution = subprocess.run(['/usr/bin/time', '-l', *command], cwd=original, env=env,
                                           capture_output=True, text=True, timeout=180)
                seconds = time.perf_counter() - start
                (dest / f'{mode}-{repeat}.log').write_text(execution.stdout + execution.stderr)
                if execution.returncode:
                    raise RuntimeError(f'{project}/{mode} failed; see {dest}/{mode}-{repeat}.log')
                rss = re.search(r'(\d+)\s+maximum resident set size', execution.stderr)
                row = dict(mode=mode, repeat=repeat, seconds=seconds, command=command,
                           max_rss_bytes=int(rss[1]) if rss else None, stdout=execution.stdout)
                if mode != 'baseline':
                    from runtime_validation.runtime_bridge import compare
                    started = time.perf_counter()
                    hybrid = compare(dest / 'static', trace, dest / f'hybrid-{mode}-{repeat}.json')
                    comparison_seconds = time.perf_counter() - started
                    observed = set()
                    excluded = 0
                    for edge in hybrid['runtime_edges']:
                        a, b = nodes.get(edge['source']), nodes.get(edge['target'])
                        if a and b and b['kind'] in ('FUNCTION', 'METHOD') and a['kind'] in ('FUNCTION', 'METHOD', 'MODULE'):
                            observed.add((pycg_scope(a['canonical_name']), pycg_scope(b['canonical_name'])))
                        else:
                            excluded += 1
                    combined = static | observed
                    added = observed - static
                    save(dest / f'added-{mode}-{repeat}.json', [
                        dict(caller=a, callee=b, in_ground_truth=(a, b) in truth_pairs)
                        for a, b in sorted(added)])
                    save(dest / f'combined-{mode}-{repeat}.json', adjacency(combined))
                    row.update(complete=hybrid['trace_complete'], trace_bytes=trace.stat().st_size,
                               comparison_seconds=comparison_seconds, observed_project_pairs=len(observed),
                               excluded_runtime_edges=excluded, bridge_summary=hybrid['summary'],
                               added_tp=len(added & truth_pairs), added_fp=len(added - truth_pairs),
                               score=grade(combined, truth))
                rows.append(row)
                save(dest / 'measurements.json', rows)
                print(project, mode, repeat, round(seconds, 3), row.get('added_tp'), row.get('added_fp'), flush=True)
        result = dict(project=project, commit=subprocess.check_output(['git', '-C', str(original), 'rev-parse', 'HEAD'], text=True).strip(),
                      files=len(files), lines=sum(len(f.read_bytes().splitlines()) for f in files),
                      parse_errors=len(facts['parse_errors']), truth_pairs=len(truth_pairs),
                      truth_entries=sum(len(bs) for bs in truth.values()),
                      static_seconds=static_seconds, static=grade(static, truth), modes={})
        for mode in ['baseline', 'calls-only', 'full']:
            group = [r for r in rows if r['mode'] == mode]
            result['modes'][mode] = dict(median_seconds=statistics.median(r['seconds'] for r in group),
                                        median_max_rss_bytes=statistics.median(r['max_rss_bytes'] for r in group))
            if mode != 'baseline':
                result['modes'][mode].update(score=group[0]['score'], added_tp=group[0]['added_tp'],
                                            added_fp=group[0]['added_fp'],
                                            median_trace_bytes=statistics.median(r['trace_bytes'] for r in group),
                                            stable_scores=all(r['score'] == group[0]['score'] for r in group))
        results.append(result)
        save(dest / 'result.json', result)
        save(out / 'results.json', results)


if __name__ == '__main__':
    main()

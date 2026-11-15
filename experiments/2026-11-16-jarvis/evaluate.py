"""Jarvis EA data projected onto independently enumerated source functions.

macOS-only resource measurement. Protocol fixed in PROTOCOL_KO.md.
"""
import argparse
import ast
import contextlib
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import shutil
import statistics
import subprocess
import sys
import time

WORKLOADS = {
    'sqlparse': ['tests'],
    'furl': ['tests', '--deselect=tests/test_furl.py::TestFurl::test_hosts',
             '--deselect=tests/test_furl.py::TestFurl::test_netloc'],
}


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def score(predicted, truth):
    tp, fp, fn = len(predicted & truth), len(predicted - truth), len(truth - predicted)
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return dict(tp=tp, fp=fp, fn=fn, precision=p, recall=r,
                f1=2 * p * r / (p + r) if p + r else 0.0)


def source_functions(files, root):
    """Independent syntax inventory: never inspect GT or resolver output."""
    names = set()
    for file in files:
        parts = list(file.relative_to(root).with_suffix('').parts)
        if parts[-1] == '__init__':
            parts.pop()
        module = '.'.join(parts)
        def walk(node, scope):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    qualified = '.'.join([scope, child.name])
                    if not isinstance(child, ast.ClassDef):
                        names.add(qualified)
                    walk(child, qualified)
                else:
                    walk(child, scope)
        walk(ast.parse(file.read_bytes()), module)
    return names


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--tool', required=True, type=Path)
    p.add_argument('--artifact', required=True, type=Path)
    p.add_argument('--python', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--rounds', type=int, default=3)
    p.add_argument('--resume', action='store_true')
    args = p.parse_args()
    tool, artifact, out = [x.resolve() for x in (args.tool, args.artifact, args.out)]
    python = args.python.absolute()
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(tool))
    from main import run
    from pycg_adapter import to_pycg, pycg_scope, adjacency
    from runtime_validation.runtime_bridge import compare
    metadata = dict(platform=platform.platform(), python=subprocess.check_output([str(python), '--version'], text=True).strip(),
                    artifact_commit=subprocess.check_output(['git', '-C', str(artifact), 'rev-parse', 'HEAD'], text=True).strip(),
                    tool_commit=subprocess.check_output(['git', '-C', str(tool), 'rev-parse', 'HEAD'], text=True).strip(),
                    dependencies=subprocess.check_output([str(python), '-m', 'pip', 'freeze'], text=True).splitlines(),
                    workloads=WORKLOADS, rounds=args.rounds,
                    scope='both endpoints are source-declared app functions; independent AST vocabulary')
    if args.resume:
        previous = json.loads((out / 'metadata.json').read_text())
        for key in ('artifact_commit', 'tool_commit', 'python', 'dependencies', 'workloads', 'scope', 'rounds'):
            if previous[key] != metadata[key]:
                raise ValueError(f'Resume metadata mismatch: {key}')
    else:
        save(out / 'metadata.json', metadata)
    results = json.loads((out / 'results.json').read_text()) if args.resume and (out / 'results.json').exists() else []
    for project, tests in WORKLOADS.items():
        if any(r['project'] == project for r in results):
            continue
        original = artifact / 'Jarvis/dataset/macro_benchmark/pj' / project
        files = sorted((original / project).rglob('*.py'))
        dest = out / project
        dest.mkdir(exist_ok=True)
        sources = dest / 'sources'
        sources.mkdir(exist_ok=True)
        for file in files:
            copy = sources / file.relative_to(original)
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, copy)
        manifest = {f.relative_to(original).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
        save(dest / 'source_sha256.json', manifest)
        vocabulary = source_functions(files, original)
        save(dest / 'function_vocabulary.json', sorted(vocabulary))
        started = time.perf_counter()
        with (dest / 'static.log').open('w') as log, contextlib.redirect_stdout(log):
            facts, symbols, graph = run(sources, dest / 'static', source_roots=['.'])
        static_seconds = time.perf_counter() - started
        internal, external, _ = to_pycg(symbols, graph, include_implicit=True)
        static_raw = internal | external
        static = {(a, b) for a, b in static_raw if a in vocabulary and b in vocabulary}
        gt_path = artifact / 'Jarvis/ground_truth/macro_benchmark' / project / 'EA.json'
        gt = json.loads(gt_path.read_text())
        raw_truth = {(a, b) for a, bs in gt.items() for b in bs}
        truth = {(a, b) for a, b in raw_truth if a in vocabulary and b in vocabulary}
        save(dest / 'truth_projected.json', adjacency(truth))
        save(dest / 'static_projected.json', adjacency(static))
        save(dest / 'static_unprojected.json', adjacency(static_raw))
        nodes = {n['id']: n for n in graph['nodes']}
        test_args = ['-q', '-o', 'addopts=', *tests]
        env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', PYTHONPATH=str(original))
        rows = json.loads((dest / 'measurements.json').read_text()) if args.resume and (dest / 'measurements.json').exists() else []
        for repeat in range(args.rounds):
            modes = ['baseline', 'calls-only', 'full']
            for mode in modes[repeat % 3:] + modes[:repeat % 3]:
                if any(r['mode'] == mode and r['repeat'] == repeat for r in rows):
                    continue
                if any(r['mode'] == mode and r.get('status') == 'timeout' for r in rows):
                    continue  # Do not spend another budget on a timed-out mode.
                trace = dest / f'{mode}-{repeat}.json'
                if mode == 'baseline':
                    command = [str(python), '-m', 'pytest', *test_args]
                else:
                    command = [str(python), str(tool / 'dynamic_analysis.py'), 'record', str(original),
                               '--module', 'pytest', '--python', str(python), '--source-root', '.', '--out', str(trace)]
                    if mode == 'calls-only':
                        command += ['--calls-only']
                    command += ['--', *test_args]
                started = time.perf_counter()
                process = subprocess.Popen(['/usr/bin/time', '-l', *command], cwd=original, env=env,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                           start_new_session=True)
                try:
                    stdout, stderr = process.communicate(timeout=240)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    stdout, stderr = process.communicate(timeout=10)
                    (dest / f'{mode}-{repeat}.log').write_text(stdout + stderr)
                    rows.append(dict(mode=mode, repeat=repeat, status='timeout', limit_seconds=240,
                                     seconds=time.perf_counter()-started, command=command))
                    save(dest / 'measurements.json', rows)
                    print(project, mode, repeat, 'timeout', flush=True)
                    continue
                execution = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
                seconds = time.perf_counter() - started
                (dest / f'{mode}-{repeat}.log').write_text(execution.stdout + execution.stderr)
                if execution.returncode:
                    raise RuntimeError(f'{project}/{mode} failed: {dest}/{mode}-{repeat}.log')
                rss = re.search(r'(\d+)\s+maximum resident set size', execution.stderr)
                row = dict(mode=mode, repeat=repeat, seconds=seconds, max_rss_bytes=int(rss[1]) if rss else None,
                           stdout=execution.stdout, command=command)
                if mode != 'baseline':
                    started = time.perf_counter()
                    hybrid = compare(dest / 'static', trace)
                    comparison_seconds = time.perf_counter() - started
                    observed, outside = set(), 0
                    for edge in hybrid['runtime_edges']:
                        a, b = nodes.get(edge['source']), nodes.get(edge['target'])
                        pair = (pycg_scope(a['canonical_name']), pycg_scope(b['canonical_name'])) if a and b else None
                        if pair and pair[0] in vocabulary and pair[1] in vocabulary:
                            observed.add(pair)
                        else:
                            outside += 1
                    combined, added = static | observed, observed - static
                    save(dest / f'observed-{mode}-{repeat}.json', adjacency(observed))
                    save(dest / f'combined-{mode}-{repeat}.json', adjacency(combined))
                    save(dest / f'added-{mode}-{repeat}.json', [dict(caller=a, callee=b, in_gt=(a, b) in truth) for a, b in sorted(added)])
                    save(dest / f'missing-{mode}-{repeat}.json', [dict(caller=a, callee=b, caller_observed=any(x==a for x,y in observed)) for a,b in sorted(truth-combined)])
                    row.update(comparison_seconds=comparison_seconds, complete=hybrid['trace_complete'],
                               score=score(combined, truth), added_tp=len(added & truth), added_fp=len(added - truth),
                               observed_pairs=len(observed), excluded_runtime_edges=outside,
                               bridge_summary=hybrid['summary'], trace_bytes=trace.stat().st_size)
                    if not row['complete']:
                        raise RuntimeError(f'Incomplete trace: {trace}')
                rows.append(row)
                save(dest / 'measurements.json', rows)
                print(project, mode, repeat, round(seconds, 3), row.get('added_tp'), row.get('added_fp'), flush=True)
        result = dict(project=project, files=len(files), lines=sum(len(f.read_bytes().splitlines()) for f in files),
                      source_functions=len(vocabulary), raw_truth_pairs=len(raw_truth), truth_pairs=len(truth),
                      excluded_truth_pairs=len(raw_truth-truth), static_pairs=len(static), parse_errors=facts['parse_errors'],
                      gt_sha256=hashlib.sha256(gt_path.read_bytes()).hexdigest(), static_seconds=static_seconds,
                      static=score(static, truth), modes={})
        for mode in ['baseline', 'calls-only', 'full']:
            group = [r for r in rows if r['mode']==mode and r.get('status')!='timeout']
            if not group:
                result['modes'][mode] = dict(status='timeout', limit_seconds=240, completed_repeats=0)
                continue
            summary = dict(median_seconds=statistics.median(r['seconds'] for r in group),
                           median_max_rss_bytes=statistics.median(r['max_rss_bytes'] for r in group))
            if mode != 'baseline':
                summary.update(score=group[0]['score'], added_tp=group[0]['added_tp'], added_fp=group[0]['added_fp'],
                               observed_pairs=group[0]['observed_pairs'],
                               median_trace_bytes=statistics.median(r['trace_bytes'] for r in group),
                               total_seconds=static_seconds+statistics.median(r['seconds']+r['comparison_seconds'] for r in group),
                               stable_scores=all(r['score']==group[0]['score'] for r in group))
            result['modes'][mode] = summary
        results.append(result)
        save(dest / 'result.json', result)
        save(out / 'results.json', results)


if __name__ == '__main__':
    main()

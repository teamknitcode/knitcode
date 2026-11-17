"""Compare baseline, calls-only and full collection on identical local inputs.

macOS: /usr/bin/time -l reports command-level maximum resident set size.
This is not the sum of concurrent process memory. Outputs include raw logs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tool', type=Path, required=True)
    parser.add_argument('--python', type=Path, required=True)
    parser.add_argument('--requests', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--rounds', type=int, default=3)
    args = parser.parse_args()
    tool, python, requests, out = [p.resolve() for p in
                                  (args.tool, args.python, args.requests, args.out)]
    # Preserve a venv executable path (resolving its symlink loses the venv).
    python = args.python.absolute()
    out.mkdir(parents=True, exist_ok=True)
    fixture = out / 'fixture'
    fixture.mkdir(exist_ok=True)
    (fixture / 'app.py').write_text('''class EmailWorker:
    def run(self, value):
        return value + 1

class FileWorker:
    def run(self, value):
        return value - 1

def dispatch(worker, name, value):
    return getattr(worker, name)(value)

def main():
    worker = EmailWorker()
    total = 0
    for value in range(1000):
        total += dispatch(worker, "".join(["r", "un"]), value)
    assert total == 500500
    print("fixture-ok", total)

main()
''', encoding='utf-8')
    targets = [
        ('dispatch', fixture, ['app.py'], ['--script', 'app.py']),
        ('requests', requests,
         ['-m', 'pytest', 'tests/test_structures.py', 'tests/test_hooks.py', '-q', '-o', 'addopts='],
         ['--module', 'pytest']),
    ]
    modes = ['baseline', 'calls-only', 'full']
    rows = []
    for name, root, normal_args, entry in targets:
        destination = out / name
        destination.mkdir(exist_ok=True)
        env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
                   PYTHONPATH=os.pathsep.join([str(root / 'src'), str(root)]))
        static_command = [str(python), str(tool / 'main.py'), str(root),
                          '--output-dir', str(destination / 'static')]
        static = subprocess.run(static_command, capture_output=True, text=True, env=env, timeout=120)
        (destination / 'static.log').write_text(static.stdout + static.stderr)
        if static.returncode:
            raise RuntimeError('Static analysis failed: ' + name)
        for repeat in range(args.rounds):
            # Rotate execution order to reduce fixed-order bias.
            for mode in modes[repeat % 3:] + modes[:repeat % 3]:
                trace = destination / f'{mode}-{repeat}.json'
                if mode == 'baseline':
                    command = [str(python), *normal_args]
                else:
                    command = [str(python), str(tool / 'dynamic_analysis.py'), 'record', str(root),
                               *entry, '--python', str(python), '--out', str(trace)]
                    if mode == 'calls-only':
                        command += ['--calls-only']
                    if name == 'requests':
                        command += ['--', *normal_args[2:]]
                started = time.perf_counter()
                result = subprocess.run(['/usr/bin/time', '-l', *command], cwd=root, env=env,
                                        capture_output=True, text=True, timeout=120)
                wall = time.perf_counter() - started
                (destination / f'{mode}-{repeat}.log').write_text(result.stdout + result.stderr)
                rss = re.search(r'(\d+)\s+maximum resident set size', result.stderr)
                row = dict(target=name, mode=mode, repeat=repeat, seconds=wall,
                           max_rss_bytes=int(rss[1]) if rss else None,
                           exit_code=result.returncode, command=command, stdout=result.stdout)
                if result.returncode:
                    raise RuntimeError(f'Execution failed: {name}/{mode}: {result.stderr}')
                if mode != 'baseline':
                    data = json.loads(trace.read_text())
                    hybrid = destination / f'hybrid-{mode}-{repeat}.json'
                    comparison = subprocess.run([
                        str(python), str(tool / 'dynamic_analysis.py'), 'compare',
                        '--static-dir', str(destination / 'static'), '--trace', str(trace),
                        '--out', str(hybrid)], capture_output=True, text=True, timeout=120)
                    if comparison.returncode:
                        raise RuntimeError(comparison.stderr)
                    row.update(trace_bytes=trace.stat().st_size, complete=data['complete'],
                               comparison=json.loads(hybrid.read_text())['summary'])
                rows.append(row)
                print(name, mode, repeat, round(wall, 3), flush=True)
        (out / 'measurements.json').write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    summaries = []
    for name, *_ in targets:
        base = statistics.median(r['seconds'] for r in rows if r['target'] == name and r['mode'] == 'baseline')
        for mode in modes:
            group = [r for r in rows if r['target'] == name and r['mode'] == mode]
            median = statistics.median(r['seconds'] for r in group)
            summaries.append(dict(target=name, mode=mode, median_seconds=median,
                                  slowdown=median / base,
                                  median_max_rss_bytes=statistics.median(r['max_rss_bytes'] for r in group),
                                  median_trace_bytes=statistics.median(r.get('trace_bytes', 0) for r in group),
                                  comparison=group[0].get('comparison')))
    result = dict(platform=platform.platform(), rounds=args.rounds,
                  tool_source_sha256={str(p.relative_to(tool)): hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in [tool / 'dynamic_analysis.py', *sorted((tool / 'runtime_validation').glob('*.py'))]},
                  tool_commit=subprocess.check_output(['git', '-C', str(tool), 'rev-parse', 'HEAD'], text=True).strip(),
                  target_commit=subprocess.check_output(['git', '-C', str(requests), 'rev-parse', 'HEAD'], text=True).strip(),
                  python=subprocess.check_output([str(python), '--version'], text=True).strip(),
                  dependencies=subprocess.check_output([str(python), '-m', 'pip', 'freeze'], text=True).splitlines(),
                  summary=summaries)
    (out / 'summary.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()

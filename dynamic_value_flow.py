"""Write a separate dynamic_value_flow JSON from a saved trace or a fresh Python run."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from runtime_validation.profile_collector import write_json_atomic
from symbol_builder import load_json


def _publish(out, data):
    # Publish a complete file. Concurrent runs cannot replace each other's output.
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=out.parent, delete=False) as stream:
            staging = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        if os.name == 'nt':
            staging.rename(out)
        else:
            os.link(staging, out)
    finally:
        if staging is not None:
            staging.unlink(missing_ok=True)


def _extension_copy(path, static_dir, result):
    data = load_json(path)
    graph = load_json(static_dir / 'graph_result.json')
    if ('dynamic_value_flow' in data or 'value_flow' not in data
            or data['value_flow'] != graph.get('value_flow')):
        raise ValueError('Expected an original VS Code export from the same static analysis')
    node_ids = {n['id'] for n in data.get('nodes', [])}
    edge_ids = {(e['source'], e['target'], (e.get('evidence') or {}).get('call_id'))
                for e in data.get('edges', []) if e['type'] == 'calls'}
    flow = result['dynamic_value_flow']
    if (not set(flow['functions']).issubset(node_ids) or
            any((s['caller'], t, s['call_id']) not in edge_ids for s in flow['call_sites'] for t in s['targets'])):
        raise ValueError('Dynamic nodes or call IDs do not match this VS Code export')
    return {**data, **result}


def _capture(args, target_args, directory):
    from ast_parser import SKIP_DIRS, detect_source_roots

    root = Path(args.project).resolve()
    cwd = (root / args.cwd).resolve()
    if not root.is_dir() or not cwd.is_dir():
        raise ValueError('Project and working directory must exist')
    script = (root / args.script).resolve() if args.script else None
    if script and (not script.is_relative_to(root) or not script.is_file() or script.suffix != '.py'):
        raise ValueError('--script must be a Python file inside the project')
    roots = args.source_root if args.source_root is not None else detect_source_roots(root)
    for item in roots:
        path = (root / item).resolve()
        if not path.is_relative_to(root) or not path.is_dir():
            raise ValueError(f'Invalid source root: {item}')
    trace = directory / 'trace.json'
    config = {'root': str(root), 'cwd': str(cwd), 'script': str(script) if script else None,
              'module': args.module, 'source_roots': roots, 'args': target_args, 'trace': str(trace),
              'symbols': str((args.static_dir / 'symbol_result.json').resolve()),
              'skip_dirs': sorted(SKIP_DIRS | {'.knitcode-runs'})}
    config_path = directory / 'config.json'
    write_json_atomic(config_path, config)
    python = str(Path(args.python).absolute()) if Path(args.python).is_file() else args.python
    result = subprocess.run([python, str(Path(__file__).resolve()), '_capture', str(config_path)], cwd=cwd)
    if not trace.is_file():
        raise RuntimeError(f'Target exited with status {result.returncode} before a trace could be saved')
    return trace, result.returncode


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ['_capture']:
        from runtime_validation.value_flow_capture import run_worker
        run_worker(load_json(argv[1]))
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--static-dir', required=True, type=Path, help='Directory with saved graph and symbols')
    parser.add_argument('--out', required=True, type=Path, help='New JSON file to create')
    parser.add_argument('--vscode-data', type=Path, help='Include an existing VS Code export in the new file')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--trace', type=Path, help='Read a saved dynamic_analysis.py record trace')
    source.add_argument('--project', type=Path, help='Execute an entry point for per-call argument types')
    entry = parser.add_mutually_exclusive_group()
    entry.add_argument('--script')
    entry.add_argument('--module')
    parser.add_argument('--python', help='Target interpreter for a fresh run')
    parser.add_argument('--cwd', help='Working directory relative to project')
    parser.add_argument('--source-root', action='append', help='Repeatable project-relative import root')
    target_args = []
    if '--' in argv:
        split = argv.index('--')
        argv, target_args = argv[:split], argv[split + 1:]
    args = parser.parse_args(argv)
    if args.project and not (args.script or args.module):
        parser.error('--project requires --script or --module')
    if args.trace and any((args.script, args.module, args.python, args.cwd, args.source_root, target_args)):
        parser.error('Target execution options require --project')
    args.cwd = args.cwd or '.'
    args.python = args.python or sys.executable
    try:
        if os.path.lexists(args.out):
            raise ValueError(f'Output already exists. Choose a new path: {args.out}')
        for filename in ('graph_result.json', 'symbol_result.json'):
            if not (args.static_dir / filename).is_file():
                raise ValueError(f'Missing static input: {args.static_dir / filename}')
        from runtime_validation.dynamic_value_flow import build_flow
        with tempfile.TemporaryDirectory(prefix='knitcode-value-flow-') as temp:
            trace, status = (args.trace, None) if args.trace else _capture(args, target_args, Path(temp))
            result = build_flow(args.static_dir, trace, capture=bool(args.project), exit_code=status)
            if args.vscode_data:
                result = _extension_copy(args.vscode_data, args.static_dir, result)
            _publish(args.out, result)
        flow = result['dynamic_value_flow']
        print(f"{len(flow['functions'])} functions, {len(flow['call_sites'])} linked call sites -> {args.out}")
        if status:
            return status if 0 < status < 256 else 1
        return int(not flow['trace_complete'])
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())

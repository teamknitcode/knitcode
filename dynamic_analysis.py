"""Execute a local script/module with sys.setprofile, or compare its trace.

python dynamic_analysis.py record PROJECT --script app.py --out out/trace.json -- ARGS
python dynamic_analysis.py record PROJECT --module package --out out/trace.json
python dynamic_analysis.py compare --static-dir output --trace out/trace.json --out out/hybrid.json
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import uuid

from runtime_validation.profile_collector import write_json_atomic

TOOL_FILE = Path(__file__).resolve()


def _execute(config):
    """Keep a real __main__ module alive through threads and atexit work."""
    module = types.ModuleType('__main__')
    sys.modules['__main__'] = module
    if config['script']:
        file = config['script']
        module.__dict__.update(__file__=file, __package__=None, __spec__=None,
                               __cached__=None,
                               __loader__=importlib.machinery.SourceFileLoader('__main__', file))
        code = compile(Path(file).read_bytes(), file, 'exec', dont_inherit=True)
    else:
        name = config['module']
        spec = importlib.util.find_spec(name)
        if spec is not None and spec.submodule_search_locations is not None:
            name += '.__main__'
            spec = importlib.util.find_spec(name)
        if spec is None or spec.loader is None or spec.submodule_search_locations is not None:
            raise ImportError(f'Cannot execute module: {name}')
        code = spec.loader.get_code(name)
        if code is None:
            raise ImportError(f'No Python code for module: {name}')
        module.__dict__.update(__file__=spec.origin, __package__=spec.parent,
                               __spec__=spec, __cached__=spec.cached, __loader__=spec.loader)
        sys.argv[0] = spec.origin
    exec(code, module.__dict__)


def _worker(config_path):
    config = json.loads(Path(config_path).read_text(encoding='utf-8'))
    root = Path(config['root'])
    os.chdir(config['cwd'])
    # Remove the analysis tool directory from the target's import search path.
    sys.path = [p for p in sys.path if p and Path(p).resolve() != TOOL_FILE.parent]
    paths = [str(root / p) for p in config['source_roots']]
    entry_path = str(Path(config['script']).parent) if config['script'] else config['cwd']
    sys.path[:0] = list(dict.fromkeys([entry_path, *paths, str(root)]))
    sys.argv = [config['script'] or config['module'], *config['args']]
    from runtime_validation.runtime_session import start_session
    session = start_session(config_path, primary=True, install_hooks=config['children'])
    try:
        _execute(config)
    except SystemExit as exc:
        session.outcome['exit_code'] = (exc.code if isinstance(exc.code, int)
                                       else int(exc.code is not None))
        raise
    except BaseException as exc:
        session.outcome['exit_code'] = 130 if isinstance(exc, KeyboardInterrupt) else 1
        session.outcome['exception'] = {'type': type(exc).__name__, 'message': str(exc)}
        raise


def _child_environment(config_path, run_directory):
    bootstrap = run_directory / 'bootstrap'
    bootstrap.mkdir()
    # Execute an existing startup hook before installing our process collector.
    source = '''import importlib.machinery
import importlib.util
import os
import sys
_directory = os.path.dirname(__file__)
_paths = [p for p in sys.path if os.path.realpath(p) != os.path.realpath(_directory)]
_spec = importlib.machinery.PathFinder.find_spec('sitecustomize', _paths)
if _spec is not None and _spec.loader is not None:
    _previous = importlib.util.module_from_spec(_spec)
    sys.modules['sitecustomize'] = _previous
    _spec.loader.exec_module(_previous)
_tool = TOOL_DIRECTORY
sys.path.insert(0, _tool)
from runtime_validation.runtime_session import bootstrap as _start
_start()
sys.path.remove(_tool)
sys.path[:] = [p for p in sys.path if os.path.realpath(p) != os.path.realpath(_directory)]
'''.replace('TOOL_DIRECTORY', repr(str(TOOL_FILE.parent)))
    (bootstrap / 'sitecustomize.py').write_text(source, encoding='utf-8')
    env = dict(os.environ, KNITCODE_PROFILE_CONFIG=str(config_path))
    env['PYTHONPATH'] = os.pathsep.join(filter(None, [str(bootstrap), env.get('PYTHONPATH')]))
    return env


def record(root, out, *, script=None, module=None, python=None, cwd=None,
           source_roots=None, target_args=(), coverage=True, variables=True,
           children=True, child_wait=10):
    """Run a fresh interpreter. All paths are resolved before changing cwd."""
    from ast_parser import SKIP_DIRS, detect_source_roots

    root, out = Path(root).resolve(), Path(out).resolve()
    if not root.is_dir():
        raise ValueError(f'Project directory does not exist: {root}')
    if bool(script) == bool(module):
        raise ValueError('Choose exactly one of --script and --module')
    if script:
        script = (root / script).resolve()
        if not script.is_file() or script.suffix != '.py' or not script.is_relative_to(root):
            raise ValueError('--script must be a local .py file inside the project root')
        if out == script:
            raise ValueError('--out must differ from the target script')
    cwd = (root / cwd).resolve() if cwd else root
    if not cwd.is_dir():
        raise ValueError(f'Working directory does not exist: {cwd}')
    source_roots = detect_source_roots(root) if source_roots is None else source_roots
    normalized_roots = []
    for entry in source_roots:
        path = (root / entry).resolve()
        if not path.is_dir() or not path.is_relative_to(root):
            raise ValueError(f'Invalid source root: {entry}')
        normalized_roots.append(path.relative_to(root).as_posix())
    interpreter = str(Path(python).resolve()) if python and Path(python).is_file() else python
    if child_wait < 0:
        raise ValueError('--child-wait must be non-negative')
    run_directory = out.parent / '.knitcode-runs' / uuid.uuid4().hex
    trace = run_directory / 'primary.json'
    config = {
        'root': str(root), 'script': str(script) if script else None, 'module': module,
        'cwd': str(cwd), 'source_roots': normalized_roots, 'args': list(target_args),
        'trace': str(trace), 'started_at': datetime.now(timezone.utc).isoformat(),
        'skip_dirs': sorted(SKIP_DIRS | {'.knitcode-runs'}), 'coverage': coverage,
        'variables': variables, 'children': children, 'process_directory': str(run_directory / 'processes'),
    }
    config_path = run_directory / 'config.json'
    write_json_atomic(config_path, config)
    env = _child_environment(config_path, run_directory) if children else None
    command = [interpreter or sys.executable, str(TOOL_FILE), '_worker', str(config_path)]
    result = subprocess.run(command, cwd=cwd, env=env)
    if not trace.is_file():
        raise RuntimeError(f'Worker exited with {result.returncode} without writing a trace')
    primary = json.loads(trace.read_text(encoding='utf-8'))
    from runtime_validation.process_results import collect_reports, combine
    reports, pending = collect_reports(config, wait_seconds=child_wait)
    for report in reports:
        if report['pid'] == primary['pid']:
            report['execution']['exit_code'] = result.returncode
            report['complete'] = report['complete'] and result.returncode == 0
    data = combine(primary, reports, pending)
    data['execution']['process_exit_code'] = result.returncode
    data['session_directory'] = str(run_directory)
    write_json_atomic(out, data)
    print(f"Dynamic analysis: {data['summary']['nodes']} nodes, "
          f"{data['summary']['edges']} observed edges -> {out}", flush=True)
    if not data['complete']:
        print('Trace is partial. Inspect execution, profile_hooks_intact and collector_errors.', flush=True)
    return data


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ['_worker']:
        _worker(argv[1])
        return 0
    parser = argparse.ArgumentParser(description='Local sys.setprofile dynamic call analysis')
    commands = parser.add_subparsers(dest='command', required=True)
    recorder = commands.add_parser('record', help='Execute a local Python entry point')
    recorder.add_argument('root', help='Local project directory')
    entry = recorder.add_mutually_exclusive_group(required=True)
    entry.add_argument('--script', help='Project-relative or absolute .py entry file')
    entry.add_argument('--module', help='Module/package to execute as python -m')
    recorder.add_argument('--out', required=True, help='Output JSON, relative to the invoking cwd')
    recorder.add_argument('--python', help='Target environment Python executable')
    recorder.add_argument('--cwd', help='Target working directory, relative to project root')
    recorder.add_argument('--source-root', action='append', default=None,
                          help='Project-relative import root, repeatable (auto-detect src by default)')
    recorder.add_argument('--calls-only', action='store_true', help='Collect calls and types with line/opcode tracing disabled')
    recorder.add_argument('--no-children', action='store_true', help='Collect the entry process only')
    recorder.add_argument('--child-wait', type=float, default=10,
                          help='Seconds to wait for outstanding child reports after the entry process exits')
    comparer = commands.add_parser('compare', help='Map observed calls to a saved static graph')
    comparer.add_argument('--static-dir', required=True)
    comparer.add_argument('--trace', required=True)
    comparer.add_argument('--out', required=True)
    target_args = []
    if argv[:1] == ['record'] and '--' in argv:
        split = argv.index('--')
        argv, target_args = argv[:split], argv[split + 1:]
    args = parser.parse_args(argv)
    try:
        if args.command == 'record':
            data = record(args.root, args.out, script=args.script, module=args.module,
                          python=args.python, cwd=args.cwd, source_roots=args.source_root,
                          target_args=target_args, coverage=not args.calls_only,
                          variables=not args.calls_only, children=not args.no_children,
                          child_wait=args.child_wait)
            status = data['execution']['process_exit_code']
            if status:
                return status if 0 < status < 256 else 1
            return int(not data['complete'])
        from runtime_validation.runtime_bridge import compare
        data = compare(args.static_dir, args.trace, args.out)
        print(f"Static comparison: {data['summary']} -> {Path(args.out).resolve()}")
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())

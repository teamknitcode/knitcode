"""Install one collector per Python interpreter and persist process outcomes."""
from __future__ import annotations

import atexit
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import threading
import time

from runtime_validation.profile_collector import ProfileCollector, write_json_atomic

ACTIVE_SESSION = None


class RuntimeSession:
    def __init__(self, config_path, *, primary=False):
        self.config_path = str(config_path)
        self.config = json.loads(Path(config_path).read_text(encoding='utf-8'))
        self.primary = primary
        self.closed = False
        self.started = time.monotonic()
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.pid = os.getpid()
        self.directory = Path(self.config['process_directory'])
        self.output = (Path(self.config['trace']) if primary else self.directory / f'{self.pid}.json')
        self.outcome = {'exit_code': 0 if primary else None, 'exception': None,
                        'thread_exceptions': [], 'unraisable_exceptions': []}
        tool = Path(__file__).resolve().parents[1]
        self.collector = ProfileCollector(
            self.config['root'], skip_dirs=self.config['skip_dirs'],
            excluded_files=[tool / 'dynamic_analysis.py', *Path(__file__).parent.glob('*.py')],
            coverage=self.config['coverage'], variables=self.config['variables'])
        self.previous_exception_hook = sys.excepthook
        self.previous_thread_hook = threading.excepthook
        self.previous_unraisable_hook = sys.unraisablehook
        sys.excepthook = self.exception_hook
        threading.excepthook = self.thread_exception
        sys.unraisablehook = self.unraisable_exception
        write_json_atomic(self.directory / f'started-{self.pid}.json', {
            'pid': self.pid, 'parent_pid': os.getppid(), 'report': str(self.output),
            'started_at': self.started_at, 'primary': primary})
        atexit.register(self.finish)
        self.collector.start()

    def exception_hook(self, kind, value, traceback):
        self.outcome['exit_code'] = 1
        self.outcome['exception'] = {'type': kind.__name__, 'message': str(value)}
        self.previous_exception_hook(kind, value, traceback)

    def thread_exception(self, args):
        self.outcome['thread_exceptions'].append({'type': args.exc_type.__name__, 'message': str(args.exc_value)})
        self.previous_thread_hook(args)

    def unraisable_exception(self, args):
        self.outcome['unraisable_exceptions'].append({'type': args.exc_type.__name__, 'message': str(args.exc_value)})
        self.previous_unraisable_hook(args)

    def finish(self, exit_code=None):
        if self.closed:
            return
        self.closed = True
        if exit_code is not None:
            self.outcome['exit_code'] = exit_code
        data = self.collector.finish()
        sys.excepthook = self.previous_exception_hook
        threading.excepthook = self.previous_thread_hook
        sys.unraisablehook = self.previous_unraisable_hook
        data['schema_version'] = 2
        data['parent_pid'] = os.getppid()
        data['execution'] = {
            'started_at': self.started_at, 'duration_seconds': time.monotonic() - self.started,
            'script': self.config['script'] if self.primary else (sys.argv[0] if sys.argv else None),
            'module': self.config['module'] if self.primary else None,
            'cwd': str(Path.cwd()), 'args': self.config['args'] if self.primary else sys.argv[1:],
            'source_roots': self.config['source_roots'], **self.outcome,
        }
        data['complete'] = (self.outcome['exit_code'] in (0, None) and data['profile_hooks_intact']
                            and not data['collector_errors'] and not self.outcome['thread_exceptions']
                            and not self.outcome['unraisable_exceptions'])
        write_json_atomic(self.output, data)


def _python_command(command):
    if isinstance(command, (str, bytes)):
        command = shlex.split(os.fsdecode(command), posix=os.name != 'nt')
    if not command:
        return False
    name = Path(os.fsdecode(command[0]).strip('"')).name.lower()
    return name.startswith(('python', 'pypy'))


def _request(pid, kind):
    session = ACTIVE_SESSION
    if session is not None:
        write_json_atomic(session.directory / f'requested-{pid}.json', {
            'pid': pid, 'parent_pid': os.getpid(), 'kind': kind})


def _exit_status(pid, status):
    session = ACTIVE_SESSION
    if session is not None and status is not None:
        write_json_atomic(session.directory / f'exit-{pid}.json', {'pid': pid, 'exit_code': status})


def _install_process_hooks():
    import multiprocessing.process

    original_init = subprocess.Popen.__init__
    original_wait = subprocess.Popen.wait
    original_poll = subprocess.Popen.poll
    original_start = multiprocessing.process.BaseProcess.start
    original_bootstrap = multiprocessing.process.BaseProcess._bootstrap

    def popen_init(process, *args, **kwargs):
        original_init(process, *args, **kwargs)
        process._knitcode_python = _python_command(process.args)
        if process._knitcode_python:
            _request(process.pid, 'subprocess')

    def popen_wait(process, *args, **kwargs):
        status = original_wait(process, *args, **kwargs)
        if getattr(process, '_knitcode_python', False):
            _exit_status(process.pid, status)
        return status

    def popen_poll(process, *args, **kwargs):
        status = original_poll(process, *args, **kwargs)
        if getattr(process, '_knitcode_python', False):
            _exit_status(process.pid, status)
        return status

    def process_start(process, *args, **kwargs):
        result = original_start(process, *args, **kwargs)
        _request(process.pid, 'multiprocessing')
        return result

    def process_bootstrap(process, *args, **kwargs):
        status = original_bootstrap(process, *args, **kwargs)
        session = ACTIVE_SESSION
        if session is not None and not session.primary:
            session.finish(status)
        return status

    subprocess.Popen.__init__ = popen_init
    subprocess.Popen.wait = popen_wait
    subprocess.Popen.poll = popen_poll
    multiprocessing.process.BaseProcess.start = process_start
    multiprocessing.process.BaseProcess._bootstrap = process_bootstrap


def _after_fork():
    session = ACTIVE_SESSION
    if session is None:
        return
    sys.setprofile(None)
    sys.settrace(None)
    threading.setprofile(None)
    threading.settrace(None)
    atexit.unregister(session.finish)
    frame = sys._getframe()
    while frame is not None:
        frame.f_trace = None
        frame = frame.f_back
    start_session(session.config_path, install_hooks=False)


def start_session(config_path, *, primary=False, install_hooks=True):
    global ACTIVE_SESSION
    ACTIVE_SESSION = RuntimeSession(config_path, primary=primary)
    if install_hooks:
        _install_process_hooks()
        if hasattr(os, 'register_at_fork'):
            os.register_at_fork(after_in_child=_after_fork)
    return ACTIVE_SESSION


def bootstrap():
    """Called by the temporary sitecustomize in each spawned interpreter."""
    config = os.environ.get('KNITCODE_PROFILE_CONFIG')
    if not config:
        return
    tool = Path(__file__).resolve().parents[1] / 'dynamic_analysis.py'
    driver = (len(sys.argv) > 1 and sys.argv[1] == '_worker' and
              Path(sys.argv[0]).resolve() == tool)
    if not driver:
        start_session(config)

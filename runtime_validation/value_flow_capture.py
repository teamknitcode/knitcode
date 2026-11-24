"""Optional, entry-process capture of bound argument types at individual CALL instructions."""
from __future__ import annotations

import atexit
from bisect import bisect_right
import os
from pathlib import Path
import sys
import threading
import types

from dynamic_analysis import _execute
from runtime_validation.profile_collector import ProfileCollector, write_json_atomic
from runtime_validation.python_execution import type_name
from runtime_validation.runtime_bridge import _relative
from symbol_builder import load_json


class SiteCollector(ProfileCollector):
    def __init__(self, root, *, symbols, **kwargs):
        super().__init__(root, coverage=False, variables=False, **kwargs)
        self.offsets = {}
        self.sites = {}
        self.bare_names = {(_relative(c['file'], symbols.get('repository')), c['line'], c['column'],
                            c['end_line'], c['end_column']): c['callee_text']
                           for c in symbols['calls'] if c['syntax_type'] == 'NAME'}

    def call_span(self, caller, file):
        code = caller.f_code
        instructions = self.execution.information(code, file)['instructions']
        pair = instructions.get(caller.f_lasti)
        # On some CPython versions f_lasti points inside a CALL inline cache.
        if pair is None:
            if code not in self.offsets:
                self.offsets[code] = sorted(instructions)
            offsets = self.offsets[code]
            index = bisect_right(offsets, caller.f_lasti) - 1
            pair = instructions[offsets[index]] if index >= 0 else None
        if pair:
            instruction, _ = pair
            pos = getattr(instruction, 'positions', None)
            if instruction.opname.startswith('CALL') and pos and None not in pos:
                return (pos.lineno, pos.col_offset, pos.end_lineno, pos.end_col_offset)
        return None

    def _arguments(self, frame, node):
        receiver = super()._arguments(frame, node)
        caller = frame.f_back
        if node['kind'] != 'FUNCTION' or caller is None:
            return receiver
        source = self._node(caller)
        if source is None:
            return receiver
        key = (source, node['id'], caller.f_lineno, caller.f_lasti)
        file = self.nodes[source]['file']
        if key not in self.sites:
            self.sites[key] = {'span': self.call_span(caller, file), 'argument_types': {}}
        site = self.sites[key]
        span = site['span']
        name = self.bare_names.get((file, *span)) if span else None
        if name:
            offset = self._bound_offset(caller, name, frame)
            if site.setdefault('positional_offset', offset) != offset:
                site['positional_offset'] = None
        arguments = site['argument_types']
        local = frame.f_locals
        for name in self.argument_names(frame.f_code):
            if name in local:
                arguments.setdefault(name, set()).add(type_name(local[name]))
        return receiver

    def _bound_offset(self, caller, name, frame):
        missing = object()
        for namespace in (caller.f_locals, caller.f_globals, caller.f_builtins):
            value = self.execution._namespace_value(namespace, name, missing)
            if value is not missing:
                break
        if type(value) is types.FunctionType and value.__code__ is frame.f_code:
            return 0
        if (type(value) is types.MethodType and type(value.__func__) is types.FunctionType
                and value.__func__.__code__ is frame.f_code):
            return 1
        if type(value) is type and frame.f_code.co_name == '__init__':
            return 1
        # A C callable can forward reordered or pre-bound arguments to this frame.
        return None

    def finish(self):
        trace = super().finish()
        for edge in trace['edges']:
            key = (edge['source'], edge['target'], edge['line'], edge['caller_offset'])
            if key in self.sites:
                site = self.sites[key]
                edge['call_span'] = site['span']
                if 'positional_offset' in site:
                    edge['positional_offset'] = site['positional_offset']
                edge['site_argument_types'] = {
                    name: sorted(types) for name, types in site['argument_types'].items()}
        return trace


def run_worker(config):
    """Run in a fresh interpreter. Finalize after target atexit hooks and threads."""
    root = Path(config['root'])
    os.chdir(config['cwd'])
    tool_dir = Path(__file__).resolve().parents[1]
    sys.path = [p for p in sys.path if p and Path(p).resolve() != tool_dir]
    entry = str(Path(config['script']).parent) if config['script'] else config['cwd']
    sys.path[:0] = list(dict.fromkeys([entry, *(str(root / p) for p in config['source_roots']), str(root)]))
    sys.argv = [config['script'] or config['module'], *config['args']]
    collector = SiteCollector(root, symbols=load_json(config['symbols']), skip_dirs=config['skip_dirs'],
                              excluded_files=[tool_dir / 'dynamic_value_flow.py',
                                              tool_dir / 'dynamic_analysis.py',
                                              *Path(__file__).parent.glob('*.py')])
    failed = False
    previous_thread_hook = threading.excepthook
    previous_unraisable = sys.unraisablehook

    def thread_error(args):
        nonlocal failed
        failed = True
        previous_thread_hook(args)

    def unraisable(args):
        nonlocal failed
        failed = True
        previous_unraisable(args)

    def finish():
        trace = collector.finish()
        trace['execution'] = {key: config[key] for key in ('script', 'module', 'source_roots')}
        trace['complete'] = trace['profile_hooks_intact'] and not trace['collector_errors'] and not failed
        write_json_atomic(config['trace'], trace)

    threading.excepthook = thread_error
    sys.unraisablehook = unraisable
    atexit.register(finish)
    if hasattr(os, 'register_at_fork'):
        def stop_in_child():
            collector.active = False
            sys.setprofile(None)
            threading.setprofile(None)
            atexit.unregister(finish)
        os.register_at_fork(after_in_child=stop_in_child)
    collector.start()
    _execute(config)

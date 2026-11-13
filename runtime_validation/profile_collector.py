"""Standard-library-only collection of local Python profile call events."""
from __future__ import annotations

import hashlib
import inspect
import json
import marshal
import os
from pathlib import Path
import sys
import tempfile
import threading
import tokenize

from runtime_validation.python_execution import ExecutionTracker, class_name, type_name


def source_digest(source: str) -> str:
    """Hash decoded, universal-newline source, as stored by ast_parser."""
    return hashlib.sha256(source.encode('utf-8')).hexdigest()


def write_json_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class ProfileCollector:
    """Record immediate caller/callee relations without retaining frames.

    Counts are profile 'call' events, including generator/coroutine resumptions.
    An external caller is an entry boundary, never a fabricated local edge.
    """

    def __init__(self, root, *, excluded_files=(), skip_dirs=(), coverage=True, variables=True):
        self.root = Path(root).resolve()
        self.excluded = {Path(path).resolve() for path in excluded_files}
        self.skip_dirs = set(skip_dirs)
        self.paths = {}
        self.codes = {}
        self.nodes = {}
        self.edges = {}
        self.files = {}
        self.external_calls = {}
        self.errors = []
        self.lock = threading.RLock()
        self.active = False
        self.callback = self._profile
        self.execution = ExecutionTracker(self, coverage=coverage, variables=variables)

    def _relative(self, filename):
        if filename in self.paths:
            return self.paths[filename]
        relative = None
        if filename and not filename.startswith('<'):
            path = Path(filename).resolve()
            if path not in self.excluded:
                try:
                    local_path = path.relative_to(self.root)
                    if not self.skip_dirs.intersection(local_path.parts[:-1]):
                        relative = local_path.as_posix()
                except ValueError:
                    pass
        self.paths[filename] = relative
        if relative is not None and relative not in self.files:
            try:
                with tokenize.open(path) as stream:
                    source = stream.read()
                self.files[relative] = {'sha256': source_digest(source)}
                self.execution.add_source(relative, source, str(path))
            except (OSError, UnicodeError, SyntaxError) as exc:
                self.files[relative] = {'sha256': None, 'error': str(exc)}
        return relative

    def _node(self, frame):
        code = frame.f_code
        cached = self.codes.get(id(code))
        if cached is not None:
            return cached[1]
        relative = self._relative(code.co_filename)
        node_id = None
        if relative is not None:
            # Code identity also distinguishes multiple lambdas on one line.
            digest = hashlib.sha256(marshal.dumps(code)).hexdigest()[:24]
            node_id = f'RUNTIME:{relative}:{code.co_firstlineno}:{digest}'
            if code.co_name == '<module>':
                kind = 'MODULE'
            elif code.co_name == '<lambda>':
                kind = 'LAMBDA'
            elif code.co_name.startswith('<'):
                kind = 'SYNTHETIC'
            elif code.co_flags & inspect.CO_NEWLOCALS:
                kind = 'FUNCTION'
            else:
                kind = 'CLASS_BODY'
            self.nodes.setdefault(node_id, {
                'id': node_id, 'file': relative, 'first_line': code.co_firstlineno,
                'name': code.co_name, 'qualified_name': getattr(code, 'co_qualname', None),
                'kind': kind, 'profile_calls': 0, 'entry_events': 0,
                'resumable': bool(code.co_flags & (inspect.CO_GENERATOR |
                                                  inspect.CO_COROUTINE |
                                                  inspect.CO_ASYNC_GENERATOR)),
                'argument_types': {}, 'receiver_types': set(),
                'return_types': set(), 'yield_types': set(),
            })
        # Keep code objects alive so their id cannot be recycled during a run.
        self.codes[id(code)] = (code, node_id)
        return node_id

    @staticmethod
    def argument_names(code):
        count = code.co_argcount + code.co_kwonlyargcount
        if code.co_flags & inspect.CO_VARARGS:
            count += 1
        if code.co_flags & inspect.CO_VARKEYWORDS:
            count += 1
        return code.co_varnames[:count]

    def _arguments(self, frame, node):
        local = frame.f_locals
        for name in self.argument_names(frame.f_code):
            if name in local:
                node['argument_types'].setdefault(name, set()).add(type_name(local[name]))
        receiver = None
        code = frame.f_code
        if code.co_argcount and self.execution.is_method(node['file'], code):
            name = code.co_varnames[0]
            if name == 'self' and name in local:
                receiver = type_name(local[name])
            elif name == 'cls' and name in local and isinstance(local[name], type):
                cls = local[name]
                receiver = class_name(cls)
        if receiver is not None:
            node['receiver_types'].add(receiver)
        return receiver

    def _external(self, frame, target, kind):
        source = self._node(frame)
        if source is None:
            return
        key = (source, target, frame.f_lineno, frame.f_lasti, kind)
        entry = self.external_calls.setdefault(key, {
            'source': source, 'target': target, 'kind': kind,
            'file': self.nodes[source]['file'], 'line': frame.f_lineno,
            'caller_offset': frame.f_lasti, 'count': 0,
        })
        entry['count'] += 1

    def _profile(self, frame, event, arg):
        if event not in ('call', 'return', 'c_call') or not self.active:
            return
        try:
            with self.lock:
                if not self.active:
                    return
                if event == 'c_call':
                    name = getattr(arg, '__qualname__', getattr(arg, '__name__', '?'))
                    module = getattr(arg, '__module__', None) or 'builtins'
                    module = module if isinstance(module, str) else '?'
                    self._external(frame, f'{module}.{name}', 'native_boundary')
                    return
                target = self._node(frame)
                if event == 'return':
                    if target is not None:
                        node = self.nodes[target]
                        info = self.execution.information(frame.f_code, node['file'])
                        kind = self.execution.return_kinds.pop(id(frame), None)
                        kind = kind or self.execution.return_kind(frame, info)
                        if kind == 'return':
                            node['return_types'].add(type_name(arg))
                        elif kind == 'yield':
                            node['yield_types'].add(type_name(arg))
                    return
                if target is None:
                    if frame.f_back is not None:
                        module = frame.f_globals.get('__name__', '?')
                        module = module if isinstance(module, str) else '?'
                        name = getattr(frame.f_code, 'co_qualname', frame.f_code.co_name)
                        self._external(frame.f_back, f'{module}.{name}', 'python_external')
                    return
                self.nodes[target]['profile_calls'] += 1
                node = self.nodes[target]
                info = self.execution.information(frame.f_code, node['file'])
                receiver = None
                if not self.execution.is_resumption(frame, info):
                    receiver = self._arguments(frame, node)
                caller = frame.f_back
                source = self._node(caller) if caller is not None else None
                if source is None:
                    self.nodes[target]['entry_events'] += 1
                    return
                key = (source, target, caller.f_lineno, caller.f_lasti)
                relation = ('ENTERS_SCOPE_OBSERVED' if self.nodes[target]['kind'] in
                            ('MODULE', 'CLASS_BODY') else 'CALLS_OBSERVED')
                edge = self.edges.setdefault(key, {
                    'source': source, 'target': target, 'type': relation,
                    'file': self.nodes[source]['file'], 'line': caller.f_lineno,
                    'caller_offset': caller.f_lasti, 'count': 0, 'thread_ids': set(),
                    'receiver_types': set(),
                })
                edge['count'] += 1
                edge['thread_ids'].add(threading.get_ident())
                if receiver is not None:
                    edge['receiver_types'].add(receiver)
        except Exception as exc:
            # Preserve the target's execution if collection itself fails.
            self.errors.append({'type': type(exc).__name__, 'message': str(exc)})
            self.active = False

    def start(self):
        for directory, folders, filenames in os.walk(self.root):
            folders[:] = [folder for folder in folders if folder not in self.skip_dirs]
            for filename in filenames:
                if filename.endswith('.py'):
                    self._relative(str(Path(directory) / filename))
        self.previous_profile = sys.getprofile()
        self.previous_thread_profile = threading.getprofile()
        self.previous_trace = sys.gettrace()
        self.previous_thread_trace = threading.gettrace()
        self.active = True
        if self.execution.coverage_enabled or self.execution.variables_enabled:
            threading.settrace(self.execution.callback)
            sys.settrace(self.execution.callback)
        threading.setprofile(self.callback)
        sys.setprofile(self.callback)

    def finish(self):
        intact = (sys.getprofile() is self.callback and
                  threading.getprofile() is self.callback)
        tracing = self.execution.coverage_enabled or self.execution.variables_enabled
        if tracing:
            intact = (intact and sys.gettrace() is self.execution.callback and
                      threading.gettrace() is self.execution.callback)
        sys.setprofile(self.previous_profile)
        threading.setprofile(self.previous_thread_profile)
        if tracing:
            sys.settrace(self.previous_trace)
            threading.settrace(self.previous_thread_trace)
        with self.lock:
            self.active = False
            for file, evidence in self.files.items():
                try:
                    with tokenize.open(self.root / file) as stream:
                        evidence['sha256_after'] = source_digest(stream.read())
                except (OSError, UnicodeError, SyntaxError):
                    evidence['sha256_after'] = None
                evidence['changed_during_run'] = evidence['sha256'] != evidence['sha256_after']
            edges = [dict(edge, thread_ids=sorted(edge['thread_ids']), receiver_types=sorted(edge['receiver_types']))
                     for _, edge in sorted(self.edges.items())]
            nodes = []
            for node in sorted(self.nodes.values(), key=lambda item: item['id']):
                nodes.append(dict(node, argument_types={name: sorted(types) for name, types in node['argument_types'].items()},
                                  receiver_types=sorted(node['receiver_types']), return_types=sorted(node['return_types']),
                                  yield_types=sorted(node['yield_types'])))
            return {
                'format': 'knitcode-profile-1', 'root': str(self.root),
                'python': sys.version, 'pid': os.getpid(),
                'profile_hooks_intact': intact, 'collector_errors': list(self.errors),
                'files': dict(sorted(self.files.items())),
                'nodes': nodes,
                'edges': edges,
                'external_calls': [value for _, value in sorted(self.external_calls.items())],
                **self.execution.payload(),
                'summary': {
                    'nodes': len(self.nodes), 'edges': len(edges),
                    'profile_call_events': sum(n['profile_calls'] for n in self.nodes.values()),
                    'local_edge_events': sum(e['count'] for e in edges),
                    'entry_events': sum(n['entry_events'] for n in self.nodes.values()),
                },
            }

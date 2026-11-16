"""Python line/bytecode-branch coverage and variable binding observations."""
from __future__ import annotations

import ast
import dis
import hashlib
import inspect
import sys
import types
import warnings


def class_name(cls):
    """Read type metadata through built-in descriptors, bypassing metaclasses."""
    module = type.__dict__['__module__'].__get__(cls)
    name = type.__dict__['__qualname__'].__get__(cls)
    module = module if isinstance(module, str) else '?'
    return f'{module}.{name}'


def type_name(value):
    return class_name(type(value))


def code_key(code):
    positions = code.co_linetable
    label = f'{code.co_firstlineno}:{getattr(code, "co_qualname", code.co_name)}'
    return hashlib.sha256(label.encode() + code.co_code + positions).hexdigest()[:24]


class ExecutionTracker:
    def __init__(self, collector, *, coverage=True, variables=True):
        self.collector = collector
        self.coverage_enabled = coverage
        self.variables_enabled = variables
        self.sources = {}
        self.code_info = {}
        self.frames = {}
        self.return_kinds = {}
        self.global_writes = {}
        self.variables = {}
        self.flows = {}
        self.source_errors = []
        self.callback = self.trace

    def add_source(self, file, source, filename):
        record = {'lines': set(), 'executed': set(), 'branches': {}, 'methods': set()}
        self.sources[file] = record
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', SyntaxWarning)
                tree = ast.parse(source, filename=filename)
                code = compile(source, filename, 'exec', dont_inherit=True)
            for cls in ast.walk(tree):
                if isinstance(cls, ast.ClassDef):
                    for child in cls.body:
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            first = min([d.lineno for d in child.decorator_list] + [child.lineno])
                            record['methods'].add((first, child.name))
            self._plan(code, file)
        except (SyntaxError, ValueError) as exc:
            self.source_errors.append({'file': file, 'message': str(exc)})

    def _plan(self, code, file):
        self.information(code, file)
        for constant in code.co_consts:
            if isinstance(constant, types.CodeType):
                self._plan(constant, file)

    def information(self, code, file):
        cache = self.code_info.get(id(code))
        if cache is not None:
            return cache[1]
        instructions = list(dis.get_instructions(code))
        info = {'instructions': {}, 'previous_opcodes': {}, 'branches': {}, 'key': code_key(code)}
        source = self.sources[file]
        line = code.co_firstlineno
        for index, instruction in enumerate(instructions):
            # starts_line is a bool on Python 3.13 and a line number on 3.10-3.12.
            position = getattr(instruction, 'positions', None)
            if position is not None and position.lineno is not None:
                line = position.lineno
            elif instruction.starts_line is not None and not isinstance(instruction.starts_line, bool):
                line = instruction.starts_line
            info['instructions'][instruction.offset] = (instruction, line)
            if index:
                info['previous_opcodes'][instruction.offset] = instructions[index - 1].opname
            if line > 0 and instruction.opname not in ('RESUME', 'RETURN_GENERATOR', 'COPY_FREE_VARS'):
                source['lines'].add(line)
            conditional = (instruction.opname == 'FOR_ITER' or
                           'JUMP' in instruction.opname and 'IF' in instruction.opname)
            if not conditional or index + 1 == len(instructions):
                continue
            target = instruction.argval
            if not isinstance(target, int):
                continue
            if instruction.opname == 'FOR_ITER':
                # CPython skips interpreter cleanup instructions when exhausted.
                target_index = next((i for i, item in enumerate(instructions)
                                     if item.offset == target), None)
                if target_index is not None and instructions[target_index].opname == 'END_FOR':
                    target_index += 1
                    if sys.version_info >= (3, 13) and instructions[target_index].opname == 'POP_TOP':
                        target_index += 1
                    target = instructions[target_index].offset
            branch_id = f'{info["key"]}:{instruction.offset}'
            branch = source['branches'].setdefault(branch_id, {
                'id': branch_id, 'scope': getattr(code, 'co_qualname', code.co_name),
                'line': line, 'offset': instruction.offset,
                'destinations': {target, instructions[index + 1].offset}, 'taken': set(),
            })
            info['branches'][instruction.offset] = branch
        self.code_info[id(code)] = (code, info)
        return info

    def is_resumption(self, frame, info):
        if not frame.f_code.co_flags & (inspect.CO_GENERATOR | inspect.CO_COROUTINE | inspect.CO_ASYNC_GENERATOR):
            return False
        initial = next((offset for offset, (instruction, _) in info['instructions'].items()
                        if instruction.opname == 'RESUME' and instruction.argval == 0), 0)
        return frame.f_lasti > initial

    @staticmethod
    def return_kind(frame, info):
        pair = info['instructions'].get(frame.f_lasti)
        opcode = pair[0].opname if pair is not None else ''
        if opcode in ('RETURN_VALUE', 'RETURN_CONST'):
            return 'return'
        if opcode == 'YIELD_VALUE' or (opcode == 'RESUME' and
                info['previous_opcodes'].get(frame.f_lasti) == 'YIELD_VALUE'):
            return 'yield'
        return 'unwind'

    def is_method(self, file, code):
        return (code.co_firstlineno, code.co_name) in self.sources[file]['methods']

    def _lookup(self, frame, name, opcode):
        if 'GLOBAL' in opcode:
            namespace, storage = frame.f_globals, 'global'
        else:
            namespace = frame.f_locals
            storage = 'global' if frame.f_code.co_name == '<module>' else 'local'
            if 'DEREF' in opcode:
                storage = 'closure'
        missing = object()
        value = self._namespace_value(namespace, name, missing)
        if value is not missing:
            return value, storage
        if opcode.startswith('LOAD_'):
            value = self._namespace_value(frame.f_globals, name, missing)
            if value is not missing:
                return value, 'global'
            value = self._namespace_value(frame.f_builtins, name, missing)
            if value is not missing:
                return value, 'builtin'
        return None, None

    @staticmethod
    def _namespace_value(namespace, name, missing):
        if issubclass(type(namespace), dict):
            return dict.get(namespace, name, missing)
        if class_name(type(namespace)) == 'builtins.FrameLocalsProxy':
            return namespace.get(name, missing)
        return missing

    def _variable(self, frame, state, name, opcode, line, offset, operation):
        value, storage = self._lookup(frame, name, opcode)
        if storage is None and operation != 'delete':
            return
        storage = storage or ('global' if 'GLOBAL' in opcode or frame.f_code.co_name == '<module>' else 'local')
        key = (state['node'], name, operation, line, offset, storage)
        event = self.variables.setdefault(key, {
            'node': state['node'], 'name': name, 'operation': operation,
            'line': line, 'offset': offset, 'storage': storage, 'count': 0, 'types': set(),
        })
        event['count'] += 1
        if operation != 'delete':
            event['types'].add(type_name(value))
        writes = self.global_writes if storage == 'global' else state['writes']
        binding = (id(frame.f_globals), name) if storage == 'global' else name
        if operation in ('write', 'argument'):
            writes[binding] = (key, id(value))
        elif operation == 'delete':
            writes.pop(binding, None)
        elif storage in ('local', 'global'):
            origin = writes.get(binding)
            if origin is not None and origin[1] == id(value):
                flow_key = (origin[0], key)
                self.flows[flow_key] = self.flows.get(flow_key, 0) + 1

    def _flush_write(self, frame, state):
        for name, opcode, line, offset, operation in state.pop('pending_write', []):
            self._variable(frame, state, name, opcode, line, offset, operation)

    def _bindings(self, frame, state, instruction, line):
        opcode, name = instruction.opname, instruction.argval
        combined = {
            'LOAD_FAST_LOAD_FAST': ('read', 'read'),
            'STORE_FAST_LOAD_FAST': ('write', 'read'),
            'STORE_FAST_STORE_FAST': ('write', 'write'),
        }
        if opcode in combined and isinstance(name, tuple):
            actions = [(variable, 'LOAD_FAST' if operation == 'read' else 'STORE_FAST',
                        line, instruction.offset, operation)
                       for variable, operation in zip(name, combined[opcode])]
            if combined[opcode][0] == 'write':
                state['pending_write'] = actions
            else:
                for action in actions:
                    self._variable(frame, state, *action)
            return
        if not isinstance(name, str):
            return
        if opcode.startswith(('LOAD_FAST', 'LOAD_NAME', 'LOAD_GLOBAL', 'LOAD_DEREF')):
            self._variable(frame, state, name, opcode, line, instruction.offset, 'read')
        elif opcode.startswith(('STORE_FAST', 'STORE_NAME', 'STORE_GLOBAL', 'STORE_DEREF',
                                'DELETE_FAST', 'DELETE_NAME', 'DELETE_GLOBAL', 'DELETE_DEREF')):
            operation = 'delete' if opcode.startswith('DELETE_') else 'write'
            state['pending_write'] = [(name, opcode, line, instruction.offset, operation)]

    def trace(self, frame, event, arg):
        collector = self.collector
        if not collector.active:
            return None
        try:
            with collector.lock:
                node = collector._node(frame)
                if node is None:
                    return None
                # Reaffirm on line events too, including a code object's first
                # invocation on CPython 3.13.3.
                frame.f_trace_opcodes = True
                file = collector.nodes[node]['file']
                info = self.information(frame.f_code, file)
                key = id(frame)
                if event == 'call':
                    resumed = self.is_resumption(frame, info)
                    if not resumed or key not in self.frames:
                        self.frames[key] = {'node': node, 'writes': {}}
                    state = self.frames[key]
                    if self.variables_enabled and not resumed:
                        for name in collector.argument_names(frame.f_code):
                            self._variable(frame, state, name, 'LOAD_FAST', frame.f_code.co_firstlineno,
                                           -1, 'argument')
                    return self.callback
                state = self.frames.get(key)
                if state is None:
                    return self.callback
                if event == 'exception':
                    state['unwinding'] = True
                    state.pop('pending_write', None)
                    state.pop('pending_branch', None)
                else:
                    self._flush_write(frame, state)
                if event == 'line' and self.coverage_enabled:
                    self.sources[file]['executed'].add(frame.f_lineno)
                elif event == 'opcode':
                    state['unwinding'] = False
                    branch = state.pop('pending_branch', None)
                    if branch is not None:
                        branch['taken'].add(frame.f_lasti)
                    if self.coverage_enabled and frame.f_lasti in info['branches']:
                        state['pending_branch'] = info['branches'][frame.f_lasti]
                    pair = info['instructions'].get(frame.f_lasti)
                    if self.variables_enabled and pair is not None:
                        instruction, line = pair
                        self._bindings(frame, state, instruction, line)
                elif event == 'return':
                    kind = 'unwind' if state.get('unwinding') else self.return_kind(frame, info)
                    self.return_kinds[key] = kind
                    if kind != 'yield':
                        self.frames.pop(key, None)
                return self.callback
        except Exception as exc:
            collector.errors.append({'type': type(exc).__name__, 'message': str(exc)})
            collector.active = False
            return None

    def payload(self):
        files = []
        sources = self.sources.items() if self.coverage_enabled else ()
        for file, source in sorted(sources):
            branches = [dict(branch, destinations=sorted(branch['destinations']), taken=sorted(branch['taken']))
                        for _, branch in sorted(source['branches'].items())]
            files.append({'file': file, 'executable_lines': sorted(source['lines']),
                          'executed_lines': sorted(source['executed']), 'branches': branches})
        events = []
        event_ids = {}
        for index, (key, event) in enumerate(sorted(self.variables.items())):
            event_id = f'VARIABLE:{index}'
            event_ids[key] = event_id
            events.append(dict(event, id=event_id, types=sorted(event['types'])))
        flows = [{'source': event_ids[source], 'target': event_ids[target], 'count': count}
                 for (source, target), count in sorted(self.flows.items())]
        return {'coverage': {'enabled': self.coverage_enabled, 'basis': 'CPython bytecode lines and conditional jump paths',
                             'files': files, 'source_errors': self.source_errors},
                'variables': {'enabled': self.variables_enabled, 'basis': 'name binding writes and subsequent reads',
                              'events': events, 'binding_flows': flows}}

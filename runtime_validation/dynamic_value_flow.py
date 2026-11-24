"""Project source-verified runtime type observations onto PR #7's node and call IDs."""
from __future__ import annotations

import ast
import builtins
from collections import abc, defaultdict
from functools import lru_cache
from pathlib import Path

from graph_builder import Resolver
from object_flow import ObjectFlow
from runtime_validation.runtime_bridge import _relative, compare
from symbol_builder import load_json, module_name_from_file
from value_flow import declared_types, mismatch, to_json


def _main_module(trace, symbols):
    # The legacy merged format cannot attribute a type name to one child's __main__.
    if len(trace.get('processes', [])) > 1:
        return None
    execution = trace.get('execution', {})
    if execution.get('script'):
        path = execution['script'].replace('\\', '/')
        prefix = trace['root'].replace('\\', '/').rstrip('/') + '/'
        if path.startswith(prefix):
            return module_name_from_file(path[len(prefix):], None, symbols.get('source_roots', []))
    module = execution.get('module')
    if module and module + '.__main__' in symbols.get('source_modules', []):
        return module + '.__main__'
    return module


_CONTAINERS = {'list', 'tuple', 'dict', 'set', 'frozenset'}
_ABCS = {'Sequence': abc.Sequence, 'MutableSequence': abc.MutableSequence, 'Iterable': abc.Iterable,
         'Collection': abc.Collection, 'Mapping': abc.Mapping, 'MutableMapping': abc.MutableMapping,
         'AbstractSet': abc.Set}


class TypeEntries:
    def __init__(self, flow, verified, main_module):
        self.flow = flow
        self.verified = verified
        self.main_module = main_module
        self.declaration = lru_cache(maxsize=None)(self._declaration)

    def _declaration(self, symbol_id, annotation):
        return declared_types(self.flow, annotation, self.flow.r.by_id[symbol_id])

    def verified_class(self, name):
        symbol = self.flow.r.classes.get(name)
        return symbol is not None and symbol['file'] in self.verified

    def describe(self, raw):
        name = raw.replace('.<locals>.', '.')
        if name.startswith('__main__.') and self.main_module:
            name = self.main_module + name[len('__main__'):]
        if self.verified_class(name):
            return ('instance', name)
        if name.startswith('builtins.'):
            short = name[len('builtins.'):]
            if short in _CONTAINERS:
                return ('container', short, ())
            return ('builtin', short)
        return ('external', name)

    def can_judge(self, descriptor, names):
        # Static nominal checks cannot disprove structural types, ABC registration,
        # dynamic bases, or a project class from a different source revision.
        for name in names | ({descriptor[1]} if descriptor[0] == 'instance' else set()):
            if name in self.flow.r.classes:
                order, status = self.flow.r._mro(self.flow.r.classes[name])
                if (status != 'complete' or not all(base == 'builtins.object' or self.verified_class(base)
                                                     for base in order)):
                    return False
        abstracts = names & _ABCS.keys()
        if abstracts:
            cls = getattr(builtins, descriptor[1], None)
            if not isinstance(cls, type) or any(issubclass(cls, _ABCS[name]) for name in abstracts):
                return False
        return descriptor[0] in ('builtin', 'container', 'instance')

    def entry(self, symbol_id, annotation, types, *, judge=True):
        names, resolved = self.declaration(symbol_id, annotation)
        descriptors = sorted({self.describe(raw) for raw in types})
        unknown = not descriptors or any('?' in d[1] for d in descriptors)
        observed = [to_json(d) for d in descriptors]
        for item in observed:
            if item['kind'] == 'container':
                item['elements_unknown'] = True
            # Existing traces store the runtime type, not the referent identity.
            if item['kind'] == 'builtin' and item['type'] in ('function', 'method', 'type'):
                item['kind'] = {'type': 'class'}.get(item['type'], item['type'])
        bad, detail = False, None
        if judge and resolved and not unknown:
            checkable = [d for d in descriptors if self.can_judge(d, names)
                         and d not in (('builtin', 'function'), ('builtin', 'method'), ('builtin', 'type'))]
            bad, detail = mismatch(self.flow, checkable, unknown, names, resolved)
        result = {'declared': annotation, 'declared_types': sorted(names), 'inferred': observed,
                  'unknown': unknown, 'mismatch': bad}
        if bad:
            result['mismatch_detail'] = detail
        return result


def _span(node):
    return node.lineno, node.col_offset, node.end_lineno, node.end_col_offset


def _site_arguments(node, symbol, signature, static_args, group, entries):
    positional = [a.arg for a in (*signature.posonlyargs, *signature.args)]
    keyword_names = {a.arg for a in (*signature.args, *signature.kwonlyargs)}
    annotations = symbol.get('parameter_annotations', {})
    result = []

    # A C wrapper (e.g. functools.partial) can forward to a Python frame at
    # the wrapper's CALL offset. Its bound locals still describe that frame,
    # but attributing them positionally to the wrapper arguments is unsafe.
    called_name = (node.func.id if isinstance(node.func, ast.Name) else
                   node.func.attr if isinstance(node.func, ast.Attribute) else None)
    direct = called_name == symbol['name'] or (
        symbol['name'] == '__init__' and called_name == symbol['scope'].rsplit('.', 1)[-1])
    offsets = group['offsets']
    offset = next(iter(offsets)) if len(offsets) == 1 else None
    if offsets:
        direct = offset is not None

    def add(location, expr, name):
        if not direct:
            name = None
        entry = entries.entry(symbol['id'], annotations.get(name), group['types'].get(name, ()))
        text = ast.unparse(expr)
        if location == {'keyword': None}:
            text = '**' + text
        result.append(dict(location, parameter=name, text=text, **entry))

    after_star = False
    for i, expr in enumerate(node.args):
        after_star |= isinstance(expr, ast.Starred)
        name = None
        if not after_star:
            if offsets:
                if offset is not None and i + offset < len(positional):
                    name = positional[i + offset]
            elif symbol['kind'] == 'FUNCTION' and i < len(positional):
                name = positional[i]
            elif static_args.get(i) in positional:
                # PR #7 distinguishes bound/unbound self. Never guess a receiver shift.
                name = static_args[i]
        add({'position': i}, expr, name)
    for kw in node.keywords:
        add({'keyword': kw.arg}, kw.value, kw.arg if kw.arg in keyword_names else None)
    return result


def _contains_yield(definition):
    pending = list(definition.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            return True
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            pending.extend(ast.iter_child_nodes(node))
    return False


def _functions(hybrid, flow, entries):
    functions, unmapped = {}, []
    grouped = defaultdict(list)
    for node in hybrid['runtime_observations']:
        if node['kind'] != 'FUNCTION':
            continue
        if node['static_id'] is None:
            unmapped.append({'runtime_id': node['id'], 'file': node['file'],
                            'reason': hybrid['node_mapping'][node['id']]['reason']})
        else:
            grouped[node['static_id']].append(node)
    for target, nodes in sorted(grouped.items()):
        symbol = flow.r.by_id[target]
        params = defaultdict(set)
        returns, yields = set(), set()
        for node in nodes:
            for name, raw in node['argument_types'].items():
                params[name].update(raw)
            returns.update(node['return_types'])
            yields.update(node.get('yield_types', ()))
        annotations = dict(symbol.get('parameter_annotations', {}))
        definition = flow.functions[target]
        variadic = {}
        for arg, kind in ((definition.args.vararg, 'varargs'), (definition.args.kwarg, 'varkw')):
            if arg:
                variadic[arg.arg] = kind
                annotations[arg.arg] = ast.unparse(arg.annotation) if arg.annotation else None
        names = dict.fromkeys([*symbol['parameters'], *sorted(params)])
        resumable = any(n.get('resumable') for n in nodes)
        generator = resumable and _contains_yield(definition)
        functions[target] = {
            'parameters': {name: entries.entry(target, annotations.get(name), params[name], judge=name not in variadic)
                           for name in names},
            'returns': entries.entry(target, symbol.get('return_annotation'), returns, judge=not generator)}
        for name, kind in variadic.items():
            if name in functions[target]['parameters']:
                functions[target]['parameters'][name]['binding_kind'] = kind
        if generator:
            functions[target]['execution_kind'] = 'async_generator' if symbol['async'] else 'generator'
            # CPython can expose an internal async-generator wrapper at YIELD_VALUE.
            functions[target]['yields'] = entries.entry(target, None, () if symbol['async'] else yields)
        elif resumable:
            functions[target]['execution_kind'] = 'coroutine'
    return functions, unmapped


def _sites(hybrid, flow, verified, entries, capture):
    graph = hybrid['static_graph']

    call_syntax = {(file, *_span(n)): n for file in verified for n in ast.walk(flow.modules[file])
                   if isinstance(n, ast.Call)}
    calls = {c['id']: c for c in flow.r.calls}
    by_span, by_line = defaultdict(set), defaultdict(set)
    source_calls = defaultdict(list)
    for call in calls.values():
        span = tuple(call[k] for k in ('line', 'column', 'end_line', 'end_column'))
        caller = call.get('caller_id') or f"MODULE:{call['module']}"
        source_calls[caller, span].append(call['id'])
    for edge in graph['edges']:
        call_id = (edge.get('evidence') or {}).get('call_id')
        if edge['type'] == 'CALLS' and call_id in calls:
            call = calls[call_id]
            span = tuple(call[k] for k in ('line', 'column', 'end_line', 'end_column'))
            by_span[edge['source'], edge['target'], span].add(call_id)
            by_line[edge['source'], edge['target'], call['line']].add(call_id)
    pr_sites = {s['call_id']: s for s in (graph.get('value_flow') or {}).get('call_sites', [])}
    linked = {}
    unlinked = []
    runtime_nodes = {n['id']: n for n in hybrid['runtime_observations']}
    for edge in hybrid['runtime_edges']:
        callee = runtime_nodes[edge['runtime_target']]
        if callee['kind'] != 'FUNCTION':
            continue
        caller, target = edge['source'], edge['target']
        span = edge.get('call_span')
        ids = (by_span[caller, target, tuple(span)] if span else by_line[caller, target, edge['line']])
        if (len(ids) != 1 or target not in flow.functions or
                (capture and not span) or callee.get('resumable')):
            item = {'caller': caller, 'target': target, 'line': edge['line'], 'call_id': None,
                    'caller_offset': edge['caller_offset'], 'candidate_call_ids': sorted(ids),
                    'reason': 'resumable_frame' if callee.get('resumable') else 'no_unique_verified_call'}
            # A dynamic-only edge can still have a verified source expression
            # and exact bound parameters even without a static graph edge.
            if span and not callee.get('resumable'):
                origins = source_calls[caller, tuple(span)]
                if len(origins) == 1:
                    item['source_call_id'] = origins[0]
                    item['text'] = calls[origins[0]]['source']
            if 'site_argument_types' in edge:
                item['bound_parameter_types'] = edge['site_argument_types']
            unlinked.append(item)
            continue
        call_id = next(iter(ids))
        call = calls[call_id]
        syntax = call_syntax.get((call['file'], call['line'], call['column'], call['end_line'], call['end_column']))
        if syntax is None:
            continue
        group = linked.setdefault((call_id, target), {'syntax': syntax, 'caller': caller,
                                                      'types': defaultdict(set), 'offsets': set()})
        if 'positional_offset' in edge:
            group['offsets'].add(edge['positional_offset'])
        for name, types in edge.get('site_argument_types', {}).items():
            group['types'][name].update(types)

    sites = []
    for (call_id, target), group in sorted(linked.items()):
        pr_site = pr_sites.get(call_id, {})
        bindings = {a['position']: a['parameter'] for a in pr_site.get('arguments', []) if 'position' in a}
        symbol = flow.r.by_id[target]
        args = _site_arguments(group['syntax'], symbol, flow.functions[target].args, bindings, group, entries)
        sites.append({'call_id': call_id, 'caller': group['caller'], 'targets': [target], 'line': calls[call_id]['line'],
                      'link_basis': 'instruction_span' if capture else 'caller_target_line', 'arguments': args})
    return sites, unlinked


def build_flow(static_dir, trace_path, *, capture=False, exit_code=None):
    static_dir = Path(static_dir)
    # Retain only metadata while the existing bridge loads and verifies the full trace.
    trace = {k: v for k, v in load_json(trace_path).items()
             if k in ('root', 'execution', 'processes', 'complete')}
    hybrid = compare(static_dir, trace_path)
    symbols = load_json(static_dir / 'symbol_result.json')
    if not symbols.get('analysis_sources') and (static_dir / 'ast_result.json').is_file():
        symbols['analysis_sources'] = {f['file']: f['source'] for f in
                                       load_json(static_dir / 'ast_result.json')['files'] if 'source' in f}
    flow = ObjectFlow(Resolver(symbols))
    verified = {file for file in flow.modules if
                hybrid['file_verification'].get(_relative(file, symbols.get('repository'))) == 'verified'}
    entries = TypeEntries(flow, verified, _main_module(trace, symbols))
    functions, unmapped = _functions(hybrid, flow, entries)
    sites, unlinked = _sites(hybrid, flow, verified, entries, capture)
    return {'dynamic_value_flow': {
        'schema_version': 1, 'source': 'sys.setprofile', 'scope': 'entry_process' if capture else 'saved_trace',
        'trace_complete': bool(trace['complete'] and exit_code in (None, 0)),
        'target_exit_code': exit_code if capture else trace.get('execution', {}).get('process_exit_code'),
        'file_verification': hybrid['file_verification'], 'functions': functions, 'call_sites': sites,
        'unmapped_functions': unmapped, 'unlinked_calls': unlinked}}

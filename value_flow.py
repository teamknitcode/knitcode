"""Value/type flow export: what values reach parameters, returns and call arguments.

The object-flow interpreter already computes abstract values to resolve calls.
This module turns the values it observed into type descriptions, resolves the
declared type hints separately, and reports conservative mismatches. It never
changes the call graph.

Inferred values are possibilities ("may receive"), not runtime guarantees.
`unknown` marks that values the analysis cannot model may also arrive.
"""
from __future__ import annotations

import ast
from collections import defaultdict

SCHEMA_VERSION = 1

_BUILTIN_TYPES = {'str', 'int', 'float', 'bool', 'bytes', 'complex', 'list', 'tuple', 'dict',
                  'set', 'frozenset', 'bytearray', 'object'}
# Abstract or permissive annotations: anything of these concrete types fits.
_ABSTRACT = {
    'Sequence': {'list', 'tuple', 'str', 'bytes'},
    'MutableSequence': {'list'},
    'Iterable': {'list', 'tuple', 'set', 'frozenset', 'dict', 'str', 'bytes'},
    'Collection': {'list', 'tuple', 'set', 'frozenset', 'dict', 'str', 'bytes'},
    'Mapping': {'dict'}, 'MutableMapping': {'dict'},
    'AbstractSet': {'set', 'frozenset'},
}
_GENERIC_ALIASES = {'List': 'list', 'Tuple': 'tuple', 'Dict': 'dict', 'Set': 'set',
                    'FrozenSet': 'frozenset', 'Type': 'type'}
# PEP 484 numeric tower: int is acceptable where float/complex is declared.
_NUMERIC = {'bool': {'int', 'float', 'complex'}, 'int': {'float', 'complex'}, 'float': {'complex'}}


# ---------------------------------------------------------------- describing values
def describe(flow, value, heap=None, depth=0):
    """(set of descriptor tuples, unknown flag) for an object-flow Value.

    Descriptors: ('instance', T), ('class', T), ('function', target),
    ('method', target, receiver), ('builtin', T), ('container', T, elements),
    ('external', name).
    """
    found, unknown = set(), False
    for atom in value.atoms:
        kind = atom.kind
        if kind in ('object', 'advisory_object'):
            found.add(('instance', atom.name))
        elif kind == 'reference':
            symbol = flow.r.by_id.get(atom.name)
            if symbol is None:
                unknown = True
            elif symbol['kind'] == 'CLASS':
                found.add(('class', symbol['canonical_name']))
            else:
                found.add(('function', symbol['canonical_name']))
        elif kind == 'bound_method':
            symbol = flow.r.by_id.get(atom.name)
            if symbol is None:
                unknown = True
            else:
                found.add(('method', symbol['canonical_name'], atom.receiver_class))
        elif kind == 'literal':
            found.add(('builtin', _literal_type(atom.name)))
        elif kind == 'none':
            found.add(('builtin', 'NoneType'))
        elif kind == 'container':
            container = atom.name.split(':')[0]
            elements = ()
            if heap is not None and depth == 0 and not heap.get((atom.site, '*'), _Unknown).atoms:
                items, item_unknown = set(), False
                for (site, key), item in heap.items():
                    if site == atom.site and key != '*':
                        described, extra = describe(flow, item, None, depth + 1)
                        items |= described
                        item_unknown |= extra
                elements = tuple(sorted(items, key=repr)) + ((('unknown',),) if item_unknown else ())
            found.add(('container', container, elements))
        elif kind == 'typed_value':
            found.add(('builtin', {'dict': 'dict', 'sequence': 'list'}.get(atom.receiver_class, atom.receiver_class)))
        elif kind == 'external_result':
            found.add(('external', atom.name + '()'))
        elif kind == 'external_reference':
            found.add(('external', atom.name))
        elif kind.startswith('collection_'):
            continue  # element summaries of a container atom described above
        else:
            unknown = True
    return found, unknown


class _UnknownValue:
    atoms = frozenset({'unknown'})


_Unknown = _UnknownValue()


def _literal_type(text):
    try:
        return type(ast.literal_eval(text)).__name__
    except (ValueError, SyntaxError):
        return 'object'


def to_json(descriptor):
    kind = descriptor[0]
    if kind in ('instance', 'class', 'builtin', 'external'):
        return {'kind': kind, 'type': descriptor[1]}
    if kind == 'function':
        return {'kind': 'function', 'target': descriptor[1]}
    if kind == 'method':
        return {'kind': 'method', 'target': descriptor[1], 'receiver': descriptor[2]}
    if kind == 'container':
        elements = [to_json(e) for e in descriptor[2] if e != ('unknown',)]
        result = {'kind': 'container', 'type': descriptor[1], 'elements': elements}
        if ('unknown',) in descriptor[2]:
            result['elements_unknown'] = True
        return result
    return {'kind': kind}


# ---------------------------------------------------------------- declared types
def declared_types(flow, annotation, context):
    """(set of type names, fully resolvable) for an annotation source text.

    Names are project canonical class names, builtin type names, 'NoneType',
    abstract names from _ABSTRACT, or 'Any'. Anything else makes the
    declaration not fully resolvable, and no mismatch is reported for it.
    """
    if not annotation:
        return set(), False
    try:
        node = ast.parse(annotation, mode='eval').body
    except SyntaxError:
        return set(), False
    return _declared(flow, node, context)


def _declared(flow, node, context):
    if isinstance(node, ast.Constant):
        if node.value is None:
            return {'NoneType'}, True
        if isinstance(node.value, str):
            try:
                return _declared(flow, ast.parse(node.value, mode='eval').body, context)
            except SyntaxError:
                return set(), False
        return set(), False
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left, left_ok = _declared(flow, node.left, context)
        right, right_ok = _declared(flow, node.right, context)
        return left | right, left_ok and right_ok
    if isinstance(node, ast.Subscript):
        origin = _origin(flow, node.value, context)
        short = origin.rsplit('.', 1)[-1]
        args = list(node.slice.elts) if isinstance(node.slice, ast.Tuple) else [node.slice]
        if short in ('Optional', 'Union'):
            names, ok = set(), True
            for argument in args:
                part, part_ok = _declared(flow, argument, context)
                names |= part
                ok = ok and part_ok
            if short == 'Optional':
                names.add('NoneType')
            return names, ok
        if short == 'Annotated':
            return _declared(flow, args[0], context)
        base = _GENERIC_ALIASES.get(short, short)
        if base in _BUILTIN_TYPES or base in _ABSTRACT:
            return {base}, True
        return set(), False
    if isinstance(node, (ast.Name, ast.Attribute)):
        origin = _origin(flow, node, context)
        short = origin.rsplit('.', 1)[-1]
        if origin in ('typing.Any', 'Any'):
            return {'Any'}, True
        if short in _ABSTRACT and origin.startswith(('typing.', 'collections.abc.')):
            return {short}, True
        if short in _GENERIC_ALIASES and origin.startswith('typing.'):
            return {_GENERIC_ALIASES[short]}, True
        refs = flow.refs(ast.unparse(node), context, node)
        classes = [r for r in refs if r['kind'] == 'CLASS']
        if classes:
            return {c['canonical_name'] for c in classes}, True
        if (not refs and isinstance(node, ast.Name) and node.id in _BUILTIN_TYPES
                and not _rebound(flow, node.id, context)):
            return {node.id}, True
        return set(), False
    return set(), False

def _rebound(flow, name, context):
    """A builtin type name rebound by an import or an assignment in the
    module or an enclosing scope (`str = bytes`, `import x as str`): the
    annotation may not mean the builtin, so it is not judged."""
    if name in flow.r.imports_at(context):
        return True
    scopes = [*flow.r.lexical_scopes(context.get('scope') or '<module>', context['module']), '<module>']
    return any(name in (a.get('targets') or [])
               for scope in scopes
               for a in flow.r.assignments.get((context['file'], scope), []))

def _origin(flow, node, context):
    text = ast.unparse(node)
    head, dot, tail = text.partition('.')
    imports = flow.r.imports_at(context)
    return imports.get(head, head) + ('.' + tail if dot else '')


# ---------------------------------------------------------------- compatibility
def mismatch(flow, inferred, unknown, declared, resolvable):
    """(mismatch, detail): only when every value is known and one definitely
    does not fit the fully resolved declaration."""
    if not resolvable or not declared or unknown or not inferred or 'Any' in declared or 'object' in declared:
        return False, None
    for descriptor in sorted(inferred, key=repr):
        verdict = _fits(flow, descriptor, declared)
        if verdict is False:
            shown = descriptor[1] if len(descriptor) > 1 else descriptor[0]
            return True, f"declared {' | '.join(sorted(declared))}, received {shown}"
    return False, None


def _fits(flow, descriptor, declared):
    """True / False / None (cannot decide)."""
    kind = descriptor[0]
    if kind in ('builtin', 'container'):
        concrete = descriptor[1]
        if concrete in declared:
            return True
        if any(_opaque_class(flow, name) for name in declared):
            return None  # e.g. a TypedDict / Protocol / external subclass may accept it
        if any(t in declared for t in _NUMERIC.get(concrete, ())):
            return True
        if any(concrete in _ABSTRACT[a] for a in declared if a in _ABSTRACT):
            return True
        return False
    if kind == 'instance':
        cls = flow.r.classes.get(descriptor[1])
        if descriptor[1] in declared:
            return True
        if cls is None:
            return None  # external or unknown class: hierarchy not provable
        order, status = flow.r._mro(cls)
        if status != 'complete':
            return None
        return True if any(name in declared for name in order) else False
    return None  # classes, functions, methods, external values: not judged


def _opaque_class(flow, name):
    """A declared project class whose hierarchy is not fully known in the
    project (TypedDict, Protocol, NamedTuple, external bases, builtin bases):
    a builtin value may still satisfy it."""
    cls = flow.r.classes.get(name)
    if cls is None:
        return False
    order, status = flow.r._mro(cls)
    if status != 'complete':
        return True
    return any(base != 'builtins.object' and base not in flow.r.classes for base in order)


# ---------------------------------------------------------------- recording and export
class ValueRecorder:
    """Collects described values while the object-flow interpreter runs."""

    def __init__(self):
        self.parameters = defaultdict(lambda: defaultdict(set))
        self.parameter_unknown = set()
        self.arguments = defaultdict(lambda: defaultdict(set))
        self.argument_unknown = set()
        self.argument_text = {}
        self.returns = defaultdict(set)
        self.return_unknown = set()
        self.bindings = defaultdict(set)  # (call_id, target_id) -> {True bound, False unbound, None untracked}

    def returned(self, flow, symbol_id, value, heap):
        found, unknown = describe(flow, value, heap)
        self.returns[symbol_id] |= found
        if unknown or not found:
            self.return_unknown.add(symbol_id)

    def parameter(self, flow, symbol_id, name, value, heap):
        found, unknown = describe(flow, value, heap)
        self.parameters[symbol_id][name] |= found
        if unknown or not found:
            self.parameter_unknown.add((symbol_id, name))

    def binding(self, call_id, target_id, bound):
        self.bindings[(call_id, target_id)].add(bound)

    def argument(self, flow, call_id, key, text, value, heap):
        found, unknown = describe(flow, value, heap)
        self.arguments[call_id][key] |= found
        self.argument_text[(call_id, key)] = text
        if unknown or not found:
            self.argument_unknown.add((call_id, key))


def export(flow, edges):
    """The `value_flow` section of graph_result.json."""
    recorder = flow.values
    resolver = flow.r
    functions = {}
    declared_cache = {}

    def declaration(symbol, text):
        key = (symbol['id'], text)
        if key not in declared_cache:
            context = {**symbol, 'scope': symbol.get('scope') or '<module>'}
            declared_cache[key] = declared_types(flow, text, context)
        return declared_cache[key]

    def entry(symbol, annotation, found, unknown):
        names, resolvable = declaration(symbol, annotation)
        bad, detail = mismatch(flow, found, unknown, names, resolvable)
        result = {'declared': annotation, 'declared_types': sorted(names),
                  'inferred': [to_json(d) for d in sorted(found, key=repr)],
                  'unknown': unknown, 'mismatch': bad}
        if detail:
            result['mismatch_detail'] = detail
        return result

    for symbol in resolver.symbols:
        if symbol['kind'] not in ('FUNCTION', 'METHOD') or symbol['id'] not in flow.functions:
            continue
        observed = recorder.parameters.get(symbol['id'], {})
        called = symbol['id'] in recorder.returns or symbol['id'] in recorder.return_unknown
        returned = flow.summaries.get(symbol['id'])
        if not observed and not called and returned is None:
            continue
        annotations = symbol.get('parameter_annotations') or {}
        parameters = {}
        for name in symbol.get('parameters') or []:
            found = observed.get(name, set())
            unknown = (symbol['id'], name) in recorder.parameter_unknown or not found
            parameters[name] = entry(symbol, annotations.get(name), found, unknown)
        if called:
            # Values returned to real callers.
            found = recorder.returns.get(symbol['id'], set())
            unknown = symbol['id'] in recorder.return_unknown
        elif returned is not None:
            # Never called from analyzed code (an entry point): every analysis run.
            found, unknown = describe(flow, returned)
        else:
            found, unknown = set(), True
        functions[symbol['id']] = {'parameters': parameters,
                                   'returns': entry(symbol, symbol.get('return_annotation'), found, unknown or not found)}

    targets_by_call = defaultdict(set)
    for edge in edges:
        call_id = (edge.get('evidence') or {}).get('call_id')
        if call_id and edge['type'] == 'CALLS':
            targets_by_call[call_id].add(edge['target'])
    calls = {c['id']: c for c in resolver.calls}
    call_sites = []
    for call_id in sorted(recorder.arguments):
        targets = sorted(targets_by_call.get(call_id, ()))
        call = calls.get(call_id)
        if not targets or call is None:
            continue
        arguments = []
        for key in sorted(recorder.arguments[call_id], key=lambda k: (k[0] != 'pos', str(k[1]))):
            found = recorder.arguments[call_id][key]
            unknown = (call_id, key) in recorder.argument_unknown or not found
            parameter = _parameter_for(resolver, targets, key, recorder.bindings, call_id)
            item = {'position': key[1]} if key[0] == 'pos' else {'keyword': key[1]}
            item.update(parameter=parameter, text=recorder.argument_text.get((call_id, key)),
                        inferred=[to_json(d) for d in sorted(found, key=repr)], unknown=unknown, mismatch=False)
            if parameter and len(targets) == 1:
                symbol = resolver.by_id.get(targets[0])
                annotation = (symbol.get('parameter_annotations') or {}).get(parameter) if symbol else None
                if symbol and annotation:
                    names, resolvable = declaration(symbol, annotation)
                    bad, detail = mismatch(flow, found, unknown, names, resolvable)
                    item['mismatch'] = bad
                    if detail:
                        item['mismatch_detail'] = detail
            arguments.append(item)
        call_sites.append({'call_id': call_id, 'caller': call.get('caller_id') or f"MODULE:{call['module']}",
                           'targets': targets, 'line': call.get('line'), 'arguments': arguments})
    return {'schema_version': SCHEMA_VERSION, 'functions': functions, 'call_sites': call_sites}


def _parameter_for(resolver, targets, key, bindings=None, call_id=None):
    """Parameter name an argument binds to, when every target agrees.

    A method reached through an instance (`obj.m(a)`) receives self
    implicitly; one reached through its class (`Base.m(self, a)`) receives
    it as the first argument. When the interpreter did not track which
    happened, the argument is not mapped (no parameter, no verdict)."""
    names = set()
    for target in targets:
        symbol = resolver.by_id.get(target)
        if symbol is None or symbol['kind'] not in ('FUNCTION', 'METHOD', 'CLASS'):
            return None
        params = list(symbol.get('parameters') or [])
        if symbol['kind'] == 'CLASS':
            init, _ = resolver._find_method(symbol, '__init__')
            if len(init) != 1:
                return None
            params = list(init[0].get('parameters') or [])
        decorators = symbol.get('decorators') or []
        if symbol['kind'] == 'METHOD' and 'staticmethod' not in decorators:
            seen = (bindings or {}).get((call_id, target), set())
            owner = 'CLASS:' + symbol['canonical_name'].rpartition('.')[0]
            if not seen and symbol['canonical_name'].endswith('.__init__') and (call_id, owner) in (bindings or {}):
                seen = {True}  # `Cls(...)`: the edge goes to __init__, self is the new instance
            if len(seen) != 1 or None in seen:
                return None
            if seen == {True} and params:
                params = params[1:]  # self / cls is bound, not passed
        elif symbol['kind'] == 'CLASS' and params:
            params = params[1:]  # __init__'s self is the new instance
        if key[0] == 'kw':
            names.add(key[1] if key[1] in params else None)
        else:
            names.add(params[key[1]] if key[1] < len(params) else None)
    return names.pop() if len(names) == 1 else None

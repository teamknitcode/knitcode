"""Check trusted annotation rules on live built-in containers without evaluating user code."""
import builtins

from runtime_validation.python_execution import type_name


ORDER = {'match': 0, 'partial': 1, 'mismatch': 2}
MATCH = {'status': 'match', 'reason': 'compatible_contents'}
BUILTIN_TYPES = {name: value for name, value in vars(builtins).items() if isinstance(value, type)}
BUILTIN_TYPES['NoneType'] = type(None)


def merge_checks(destination, checks):
    """Keep a representative of the strongest verdict over all calls."""
    for name, check in checks.items():
        previous = destination.get(name)
        if previous is None or ORDER[check['status']] > ORDER[previous['status']]:
            destination[name] = check


def _inherits_traversal(mro, expected):
    """A named tuple retains tuple semantics. An overridden iterator or indexing may not."""
    names = ('__iter__', '__len__', '__getitem__')
    if expected is dict:
        names += ('items', 'keys', 'values')
    for name in names:
        original = vars(expected).get(name)
        for base in mro:
            namespace = type.__dict__['__dict__'].__get__(base)
            if name in namespace:
                if namespace[name] is not original:
                    return False
                break
    return True


def _check(value, rule, path):
    kind, *args = rule
    if kind == 'union':
        # Each alternative applies to the whole value, e.g. list[int] | list[str].
        best = None
        for branch in args:
            result = _check(value, branch, path)
            if result['status'] == 'match':
                return result
            # Prefer the branch that matched the outer type when all alternatives fail.
            if (best is None or ORDER[result['status']] < ORDER[best['status']]
                    or result['status'] == best['status'] and len(result.get('path', '')) > len(best.get('path', ''))):
                best = result
        return best
    expected = BUILTIN_TYPES[args[0]]
    cls = type(value)
    mro = type.__dict__['__mro__'].__get__(cls)
    numeric = ((expected is float or expected is complex) and any(t is int for t in mro)
               or expected is complex and any(t is float for t in mro))
    if not numeric and not any(t is expected for t in mro):
        return {'status': 'mismatch', 'reason': 'incompatible_element' if path else 'incompatible_type',
                'path': path, 'observed_type': type_name(value)}
    if kind == 'nominal':
        return MATCH
    if cls is not expected and not _inherits_traversal(mro, expected):
        return {'status': 'partial', 'reason': 'custom_container', 'path': path}
    children = args[1:]
    if kind == 'tuple' and tuple.__len__(value) != len(children):
        return {'status': 'mismatch', 'reason': 'tuple_length', 'path': path,
                'expected_length': len(children), 'observed_length': tuple.__len__(value)}
    worst = MATCH
    if kind == 'dict':
        items = ((part, children[j], f'{path}[{i}].{label}')
                 for i, pair in enumerate(dict.copy(value).items())
                 for j, (label, part) in enumerate(zip(('key', 'value'), pair)))
    else:
        snapshot = expected.copy(value) if expected in (list, set) else expected.__iter__(value)
        items = ((part, children[i] if kind == 'tuple' else children[0], f'{path}[{i}]')
                 for i, part in enumerate(snapshot))
    for part, child, child_path in items:
        result = _check(part, child, child_path)
        if ORDER[result['status']] > ORDER[worst['status']]:
            worst = result
    return worst


def check_container(value, rule):
    return _check(value, rule, '')

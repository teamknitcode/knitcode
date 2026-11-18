"""Call patterns found missing on the JARVIS benchmark (2026-11-15).

Each case is a may-call that Python performs at runtime; each has a negative
counterpart so the rule does not widen beyond its evidence.
"""
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from ast_parser import scan_repository
from symbol_builder import build_symbol_result
from graph_builder import build_graph
from unresolved_classifier import reclassify_graph
from call_status import annotate_call_statuses
from verify_v23 import verify
from verify_v231 import check_status

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from jarvis_benchmark import knitcode_cg, jarvis_name, gen_table_score  # noqa: E402


class Helpers:
    def analyze(self, files):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'repo'
            root.mkdir()
            for name, source in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(textwrap.dedent(source), encoding='utf-8')
            facts = scan_repository(root)
            self.assertEqual(facts['parse_errors'], [])
            data = build_symbol_result(facts)
        graph = annotate_call_statuses(reclassify_graph(build_graph(data), data), data)
        self.assertEqual(verify(graph, data), 0)
        self.assertEqual(check_status(graph, data), 0)
        return data, graph

    def calls(self, source, caller, conventions=()):
        data, graph = self.analyze({'app.py': source})
        return set(knitcode_cg(data, graph, conventions=conventions).get(caller, []))


class JarvisImprovementTests(Helpers, unittest.TestCase):
    # -- class-body alias -------------------------------------------------
    def test_class_body_alias_of_staticmethod(self):
        self.assertIn('app.Mv.left', self.calls('''
            class Mv:
                @staticmethod
                def left(x):
                    return x
                l = left
            def run():
                Mv.l(3)
            ''', 'app.run'))

    def test_class_attribute_that_is_not_a_method_alias_stays_unresolved(self):
        calls = self.calls('''
            def helper(x):
                return x
            class Mv:
                def left(self, x):
                    return x
                l = helper
                left = None
            def run():
                Mv.l(3)
                Mv().left(1)
            ''', 'app.run')
        self.assertNotIn('app.Mv.left', calls)

    # -- f-string falls back to __str__ ----------------------------------
    def test_fstring_runs_str_without_format(self):
        calls = self.calls('''
            class Color:
                def __str__(self):
                    return 'c'
            class Fmt:
                def __format__(self, spec):
                    return 'f'
                def __str__(self):
                    return 's'
            def run():
                c = Color()
                f = Fmt()
                return f'{c}{f}'
            ''', 'app.run')
        self.assertIn('app.Color.__str__', calls)
        self.assertIn('app.Fmt.__format__', calls)
        self.assertNotIn('app.Fmt.__str__', calls)

    # -- iteration protocol ----------------------------------------------
    def test_for_loop_runs_next(self):
        calls = self.calls('''
            class It:
                def __iter__(self):
                    return self
                def __next__(self):
                    raise StopIteration
            class Box:
                def __iter__(self):
                    return It()
            def run():
                for _ in It():
                    pass
                for _ in Box():
                    pass
            ''', 'app.run')
        self.assertTrue({'app.It.__iter__', 'app.It.__next__', 'app.Box.__iter__'} <= calls)

    def test_iteration_without_project_next_adds_nothing(self):
        calls = self.calls('''
            class Box:
                def __iter__(self):
                    return iter([1])
            def run():
                for _ in Box():
                    pass
            ''', 'app.run')
        self.assertEqual({c for c in calls if c.endswith('__next__')}, set())

    # -- raise of a bare class -------------------------------------------
    def test_raise_bare_class_runs_init(self):
        calls = self.calls('''
            class Err(Exception):
                def __init__(self):
                    pass
            def run():
                raise Err
            ''', 'app.run')
        self.assertIn('app.Err.__init__', calls)

    # -- decorator application -------------------------------------------
    def test_bare_decorator_is_called_with_the_function(self):
        data, graph = self.analyze({'app.py': '''
            def dec(f):
                f()
                return f
            @dec
            def func():
                pass
            '''})
        cg = knitcode_cg(data, graph)
        self.assertIn('app.dec', cg['app'])
        self.assertIn('app.func', cg['app.dec'])

    def test_decorator_factory_applies_the_returned_decorator_once(self):
        data, graph = self.analyze({'app.py': '''
            def factory(x):
                def dec(f):
                    return f
                return dec
            @factory(1)
            def func():
                pass
            '''})
        decorator_edges = [(e['source'], e['target']) for e in graph['implicit_edges']
                           if e['evidence']['implicit_kind'] == 'decorator']
        # factory(1) is an ordinary call; its result `dec` is what decorates func.
        self.assertEqual(decorator_edges, [('MODULE:app', 'FUNCTION:app.factory.dec')])

    # -- builtin callbacks -----------------------------------------------
    def test_map_and_filter_function_callbacks(self):
        calls = self.calls('''
            def double(x):
                return 2 * x
            def keep(x):
                return x
            def run(xs):
                list(map(double, xs))
                list(filter(keep, xs))
                list(filter(None, xs))
            ''', 'app.run')
        self.assertTrue({'app.double', 'app.keep'} <= calls)

    # -- custom __setattr__ ----------------------------------------------
    def test_attribute_store_runs_custom_setattr(self):
        calls = self.calls('''
            class Url:
                def __setattr__(self, attr, value):
                    object.__setattr__(self, attr, value)
            class Plain:
                pass
            def run():
                u = Url()
                u.scheme = 'http'
                p = Plain()
                p.x = 1
            ''', 'app.run')
        self.assertIn('app.Url.__setattr__', calls)

    # -- six.add_metaclass(ABCMeta) --------------------------------------
    def test_six_add_metaclass_abcmeta_keeps_the_hierarchy(self):
        calls = self.calls('''
            import abc
            import six
            @six.add_metaclass(abc.ABCMeta)
            class Base(object):
                def load(self):
                    pass
            class Child(Base):
                def __init__(self):
                    self.load()
            def run():
                Child()
            ''', 'app.Child.__init__')
        self.assertIn('app.Base.load', calls)

    def test_six_add_metaclass_with_unknown_metaclass_stays_unknown(self):
        calls = self.calls('''
            import six
            from somewhere import Meta
            @six.add_metaclass(Meta)
            class Base(object):
                def load(self):
                    pass
            class Child(Base):
                def __init__(self):
                    self.load()
            ''', 'app.Child.__init__')
        self.assertNotIn('app.Base.load', calls)


class IdentityDecoratorTests(Helpers, unittest.TestCase):
    """Step 2a: a decorator proven to return its argument keeps the binding."""

    def test_identity_decorator_keeps_the_original_binding(self):
        calls = self.calls('''
            def dec(f):
                return f
            @dec
            def func():
                pass
            def run():
                func()
            ''', 'app.run')
        self.assertIn('app.func', calls)

    def test_identity_decorator_through_an_alias_and_nested_scope(self):
        data, graph = self.analyze({'app.py': '''
            def dec1(f):
                return f
            a = dec1
            @a
            def func():
                pass
            def outer():
                def dec(f):
                    return f
                @dec
                def inner():
                    pass
                inner()
            def run():
                func()
            '''})
        cg = knitcode_cg(data, graph)
        self.assertIn('app.func', cg['app.run'])
        self.assertIn('app.outer.inner', cg['app.outer'])

    def test_identity_decorator_factory(self):
        calls = self.calls('''
            def static_vars(**kwargs):
                def decorate(func):
                    for k in kwargs:
                        setattr(func, k, kwargs[k])
                    return func
                return decorate
            @static_vars(count=0)
            def counted():
                pass
            def run():
                counted()
            ''', 'app.run')
        self.assertIn('app.counted', calls)

    def test_decorators_that_may_replace_the_function_still_abstain(self):
        calls = self.calls('''
            def replace(f):
                return None
            def maybe(f):
                if f:
                    return f
                return print
            def rebinds(f):
                f = print
                return f
            def wraps(f):
                def inner():
                    return f()
                return inner
            def lazy(f):
                yield f
            @replace
            def a():
                pass
            @maybe
            def b():
                pass
            @rebinds
            def c():
                pass
            @wraps
            def d():
                pass
            @lazy
            def e():
                pass
            def run():
                a(); b(); c(); d(); e()
            ''', 'app.run')
        self.assertEqual(calls & {'app.a', 'app.b', 'app.c', 'app.d', 'app.e'}, set())

    def test_unknown_external_decorator_still_abstains(self):
        calls = self.calls('''
            from somewhere import dec
            @dec
            def func():
                pass
            def run():
                func()
            ''', 'app.run')
        self.assertNotIn('app.func', calls)


class ClosureTests(Helpers, unittest.TestCase):
    """Step 2b-1: values a nested function captures from its enclosing call."""

    def test_wrapper_decorator_calls_the_original_through_its_closure(self):
        data, graph = self.analyze({'app.py': '''
            def dec1(f):
                def inner():
                    return f()
                return inner
            def dec2(f):
                def inner():
                    return f()
                return inner
            @dec1
            @dec2
            def func():
                pass
            '''})
        cg = knitcode_cg(data, graph)
        self.assertEqual(set(cg['app']), {'app.dec1', 'app.dec2'})
        self.assertEqual(cg['app.dec2.inner'], ['app.func'])
        self.assertEqual(cg['app.dec1.inner'], ['app.dec2.inner'])

    def test_decorator_factory_closure_like_sqlparse_recurse(self):
        data, graph = self.analyze({'app.py': '''
            def recurse(*cls):
                def wrap(f):
                    def wrapped_f(tlist):
                        f(tlist)
                    return wrapped_f
                return wrap
            @recurse(int)
            def group_a(tlist):
                pass
            @recurse()
            def group_b(tlist):
                pass
            '''})
        cg = knitcode_cg(data, graph)
        self.assertEqual(set(cg['app']), {'app.recurse', 'app.recurse.wrap'})
        self.assertEqual(set(cg['app.recurse.wrap.wrapped_f']), {'app.group_a', 'app.group_b'})

    def test_closure_over_a_plain_local_function(self):
        calls = self.calls('''
            def work():
                pass
            def outer():
                job = work
                def run():
                    job()
                return run
            ''', 'app.outer.run')
        self.assertIn('app.work', calls)

    def test_unknown_decorator_below_makes_the_value_unknown(self):
        data, graph = self.analyze({'app.py': '''
            from somewhere import external
            def dec(f):
                def inner():
                    return f()
                return inner
            @dec
            @external
            def func():
                pass
            '''})
        cg = knitcode_cg(data, graph)
        self.assertNotIn('app.func', cg.get('app.dec.inner', []))


class DecoratedMethodBodyTests(Helpers, unittest.TestCase):
    """Step 3 C1: property and staticmethod bodies are analyzed like other methods."""

    def test_property_getter_and_setter_bodies(self):
        data, graph = self.analyze({'app.py': '''
            class Url:
                def __init__(self):
                    self._port = 0
                @property
                def port(self):
                    return self._port
                @port.setter
                def port(self, value):
                    self._port = value
                @property
                def origin(self):
                    return self.port
                @origin.setter
                def origin(self, value):
                    self.port = value
            '''})
        cg = knitcode_cg(data, graph)
        self.assertIn('app.Url.port', cg.get('app.Url.origin', []))

    def test_staticmethod_body_uses_object_flow(self):
        calls = self.calls('''
            class It:
                def __iter__(self):
                    return self
                def __next__(self):
                    raise StopIteration
            class Tools:
                @staticmethod
                def scan():
                    for _ in It():
                        pass
            ''', 'app.Tools.scan')
        self.assertTrue({'app.It.__iter__', 'app.It.__next__'} <= calls)

    def test_project_defined_property_name_is_not_trusted(self):
        data, graph = self.analyze({'app.py': '''
            def property(f):
                return f
            class Url:
                @property
                def a(self):
                    return self.b
                @property
                def b(self):
                    return 1
            '''})
        cg = knitcode_cg(data, graph)
        self.assertNotIn('app.Url.b', cg.get('app.Url.a', []))

class DynamicGetattrTests(Helpers, unittest.TestCase):
    """Step 3 C2: getattr(self, '<prefix>' + ...) dispatch to methods with that prefix."""

    def test_sqlparse_style_format_lower_dispatch(self):
        calls = self.calls('''
            class Filter:
                def _process(self, tlist):
                    func_name = '_process_{cls}'.format(cls=type(tlist).__name__)
                    func = getattr(self, func_name.lower(), self._process_default)
                    func(tlist)
                def _process_where(self, tlist):
                    pass
                def _process_case(self, tlist):
                    pass
                def _process_default(self, tlist):
                    pass
                def _processCamel(self, tlist):
                    pass
                def other(self):
                    pass
            ''', 'app.Filter._process')
        self.assertTrue({'app.Filter._process_where', 'app.Filter._process_case',
                         'app.Filter._process_default'} <= calls)
        # .lower() cannot produce an upper-case letter; unrelated names never fit.
        self.assertFalse({'app.Filter._processCamel', 'app.Filter.other'} & calls)

    def test_concatenation_and_fstring_prefixes(self):
        calls = self.calls('''
            class Handler:
                def handle(self, kind):
                    getattr(self, 'on_' + kind)()
                    getattr(self, f'do_{kind}')()
                def on_start(self):
                    pass
                def do_stop(self):
                    pass
                def helper(self):
                    pass
            ''', 'app.Handler.handle')
        self.assertTrue({'app.Handler.on_start', 'app.Handler.do_stop'} <= calls)
        self.assertNotIn('app.Handler.helper', calls)

    def test_non_static_or_too_short_names_abstain(self):
        calls = self.calls('''
            class Handler:
                def handle(self, name):
                    getattr(self, name)()
                    getattr(self, '_' + name)()
                def a(self):
                    pass
                def _b(self):
                    pass
            ''', 'app.Handler.handle')
        self.assertEqual(calls & {'app.Handler.a', 'app.Handler._b'}, set())

class ListFieldAndGeneratorTests(Helpers, unittest.TestCase):
    """Step 3 C4: list.append contents and generator bodies in the caller's context."""

    STACK = '''
        class A:
            def process(self, stream):
                return stream
        class B:
            def process(self, stream):
                return stream
        class Stack:
            def __init__(self):
                self.stmtprocess = []
            def run(self, sql):
                for stmt in sql:
                    for filter_ in self.stmtprocess:
                        filter_.process(stmt)
                    yield stmt
        def build(stack, options):
            if options.get('a'):
                stack.stmtprocess.append(A())
            if options.get('b'):
                stack.stmtprocess.append(B())
            return stack
        '''

    def test_appended_objects_reach_a_generator_run_by_the_caller(self):
        calls = self.calls(self.STACK + '''
        def fmt(sql, **options):
            stack = Stack()
            stack = build(stack, options)
            return ''.join(stack.run(sql))
        ''', 'app.Stack.run')
        self.assertEqual(calls & {'app.A.process', 'app.B.process'}, {'app.A.process', 'app.B.process'})

    def test_extend_and_pop_keep_known_elements(self):
        calls = self.calls('''
            class A:
                def go(self):
                    pass
            class B:
                def go(self):
                    pass
            def run():
                queue = []
                queue.extend([A(), B()])
                item = queue.pop()
                item.go()
            ''', 'app.run')
        self.assertEqual(calls & {'app.A.go', 'app.B.go'}, {'app.A.go', 'app.B.go'})

    def test_list_passed_to_unknown_code_is_forgotten(self):
        calls = self.calls('''
            from somewhere import fill
            class A:
                def go(self):
                    pass
            def run():
                queue = [A()]
                fill(queue)
                for item in queue:
                    item.go()
            ''', 'app.run')
        # fill() may have replaced the elements: no definite target from A alone.
        self.assertNotIn('app.A.go', calls)

    def test_extend_with_unknown_iterable_is_forgotten(self):
        calls = self.calls('''
            class A:
                def go(self):
                    pass
            def run(things):
                queue = [A()]
                queue.extend(things)
                for item in queue:
                    item.go()
            ''', 'app.run')
        self.assertNotIn('app.A.go', calls)

class DestructuringTests(Helpers, unittest.TestCase):
    """Step 4 F1: tuple/list unpacking of known literals keeps element values."""

    def test_nested_and_starred_unpacking(self):
        calls = self.calls('''
            def f1():
                pass
            def f2():
                pass
            def f3():
                pass
            def f4():
                pass
            def run():
                a, (b, c) = f1, (f2, f3)
                a(); b(); c()
                first, *middle, last = f1, f2, f3, f4
                middle[0](); middle[1](); last()
            ''', 'app.run')
        self.assertEqual(calls & {'app.f1', 'app.f2', 'app.f3', 'app.f4'},
                         {'app.f1', 'app.f2', 'app.f3', 'app.f4'})

    def test_unpacked_bound_methods_and_function_results(self):
        calls = self.calls('''
            class Box:
                def first(self):
                    pass
                def second(self):
                    pass
            def pair():
                return 1, Box()
            def run():
                box = Box()
                x, (y,) = box.first, (box.second,)
                x(); y()
                idx, token = pair()
                token.first()
            ''', 'app.run')
        self.assertTrue({'app.Box.first', 'app.Box.second'} <= calls)

    def test_wrong_length_or_unknown_value_assigns_nothing_known(self):
        calls = self.calls('''
            def f1():
                pass
            def f2():
                pass
            def f3():
                pass
            def run(things):
                a, b = f1, f2, f3
                a(); b()
                c, d = things
                c(); d()
            ''', 'app.run')
        # `a, b = f1, f2, f3` raises ValueError; `things` is unknown.
        self.assertEqual(calls & {'app.f1', 'app.f2', 'app.f3'}, set())

class SubscriptStoreTests(Helpers, unittest.TestCase):
    """Step 4 F2: literal-key stores and dict.update on fully known containers."""

    def test_dict_and_list_item_stores(self):
        calls = self.calls('''
            def f1():
                pass
            def f2():
                pass
            def f3():
                pass
            def run():
                d = {}
                d["a"] = f1
                d["a"]()
                nested = {"x": {"y": f1}}
                nested["x"]["y"] = f2
                nested["x"]["y"]()
                items = [None]
                items[0] = f3
                items[-1]()
            ''', 'app.run')
        self.assertEqual(calls & {'app.f1', 'app.f2', 'app.f3'}, {'app.f1', 'app.f2', 'app.f3'})

    def test_strong_update_replaces_the_old_value(self):
        calls = self.calls('''
            def old():
                pass
            def new():
                pass
            def run():
                d = {"a": old}
                d["a"] = new
                d["a"]()
            ''', 'app.run')
        self.assertIn('app.new', calls)
        self.assertNotIn('app.old', calls)

    def test_dict_update_copies_known_keys(self):
        calls = self.calls('''
            def f1():
                pass
            def f2():
                pass
            def run():
                d = {"a": f1}
                d.update({"a": f2})
                d["a"]()
            ''', 'app.run')
        self.assertIn('app.f2', calls)

    def test_unknown_key_or_out_of_range_index_is_not_modeled(self):
        calls = self.calls('''
            def f1():
                pass
            def f2():
                pass
            def run(key):
                d = {"a": f1}
                d[key] = f2
                d["a"]()
                items = [f1]
                items[5] = f2
            ''', 'app.run')
        # d[key] may overwrite "a": nothing definite remains for d["a"].
        self.assertEqual(calls & {'app.f1', 'app.f2'}, set())

class ReturnedValueCallTests(Helpers, unittest.TestCase):
    """Step 4 F3: calling what a call returned; values a generator yields."""

    def test_call_of_a_returned_function(self):
        data, graph = self.analyze({
            'helpers.py': '''
                def leaf():
                    pass
                def make():
                    def inner():
                        pass
                    return inner
                def pick():
                    return make
                def give():
                    return leaf
            ''',
            'app.py': '''
                from helpers import pick, give
                def run():
                    pick()()()
                    give()()
            '''})
        calls = set(knitcode_cg(data, graph)['app.run'])
        self.assertTrue({'helpers.pick', 'helpers.make', 'helpers.make.inner',
                         'helpers.give', 'helpers.leaf'} <= calls)

    def test_call_of_an_unknown_result_adds_nothing(self):
        calls = self.calls('''
            from somewhere import factory
            def leaf():
                pass
            def run():
                factory()()
            ''', 'app.run')
        self.assertNotIn('app.leaf', calls)

    def test_loop_over_a_generator_sees_yielded_values(self):
        calls = self.calls('''
            class Job:
                def go(self):
                    pass
            def task():
                pass
            def produce(n):
                for _ in range(n):
                    yield task
                yield Job()
            def run():
                for item in produce(3):
                    item()
                for job in produce(1):
                    job.go()
            ''', 'app.run')
        self.assertTrue({'app.task', 'app.Job.go'} <= calls)

    def test_generator_of_unknown_values_yields_nothing_definite(self):
        calls = self.calls('''
            def task():
                pass
            def produce(things):
                for thing in things:
                    yield thing
            def run(things):
                for item in produce(things):
                    item()
            ''', 'app.run')
        self.assertNotIn('app.task', calls)

class StarImportTests(Helpers, unittest.TestCase):
    """Step 4 F4: `from m import *` binds m's public names; later bindings win."""

    def test_later_star_import_shadows_earlier(self):
        data, graph = self.analyze({
            'first.py': 'def shared():\n    pass\ndef only_first():\n    pass\n',
            'second.py': 'def shared():\n    pass\n',
            'app.py': 'from first import *\nfrom second import *\ndef run():\n    shared()\n    only_first()\n'})
        calls = set(knitcode_cg(data, graph)['app.run'])
        self.assertEqual(calls & {'first.shared', 'second.shared', 'first.only_first'},
                         {'second.shared', 'first.only_first'})

    def test_star_reexport_chain_and_relative_package(self):
        data, graph = self.analyze({
            'pkg/__init__.py': 'from .impl import *\n',
            'pkg/impl.py': 'def work():\n    pass\n',
            'hub.py': 'from pkg import *\n',
            'app.py': 'from hub import work\ndef run():\n    work()\n'})
        self.assertIn('pkg.impl.work', knitcode_cg(data, graph)['app.run'])

    def test_private_names_and_explicit_all(self):
        data, graph = self.analyze({
            'lib.py': '__all__ = ["public"]\ndef public():\n    pass\ndef hidden():\n    pass\ndef _private():\n    pass\n',
            'other.py': 'def _secret():\n    pass\n',
            'app.py': 'from lib import *\nfrom other import *\ndef run():\n    public()\n    hidden()\n    _secret()\n'})
        calls = set(knitcode_cg(data, graph)['app.run'])
        self.assertIn('lib.public', calls)
        self.assertFalse({'lib.hidden', 'lib._private', 'other._secret'} & calls)

    def test_local_definition_after_star_import_wins(self):
        data, graph = self.analyze({
            'lib.py': 'def helper():\n    pass\n',
            'app.py': 'from lib import *\ndef helper():\n    pass\ndef run():\n    helper()\n'})
        calls = set(knitcode_cg(data, graph)['app.run'])
        self.assertIn('app.helper', calls)
        self.assertNotIn('lib.helper', calls)

class DeterminismTests(unittest.TestCase):
    """The call graph must not depend on PYTHONHASHSEED (set iteration order).

    Each item.go(W()) has eight candidate receivers, and w.work() is resolved
    only inside the caller-specific interpretation of go(). With a tiny
    analysis budget, which candidates are interpreted before the budget runs
    out is visible in the result unless candidates are visited in a fixed order.
    """

    SOURCE = '\n'.join(
        [line for c in 'ABCDEFGH' for line in (
            f'class W{c}:', '    def work(self):', '        pass',
            f'class {c}:', '    def go(self, w):', '        w.work()', '        w.work()', '        w.work()')]
        + ['def produce():'] + [f'    yield {c}()' for c in 'ABCDEFGH']
        + ['def run():'] + [f'    for item in produce():\n        item.go(W{c}())' for c in 'ABCDEFGH']) + '\n'

    SCRIPT = textwrap.dedent('''
        import contextlib, io, json, sys
        from pathlib import Path
        sys.path[:0] = [sys.argv[2], sys.argv[2] + '/scripts']
        import object_flow
        original = object_flow.ObjectFlow.__init__
        def small_budget(self, *args, **kwargs):
            original(self, *args, **kwargs)
            self.root_step_limit = 40
        object_flow.ObjectFlow.__init__ = small_budget
        from jarvis_benchmark import analyze, knitcode_cg
        with contextlib.redirect_stdout(io.StringIO()):
            _, symbols, graph = analyze(Path(sys.argv[1]))
        print(json.dumps(knitcode_cg(symbols, graph), sort_keys=True))
        ''')

    def test_same_graph_for_different_hash_seeds(self):
        import os
        import subprocess
        root_dir = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / 'repo'
            project.mkdir()
            (project / 'app.py').write_text(self.SOURCE, encoding='utf-8')
            script = Path(tmp) / 'run.py'
            script.write_text(self.SCRIPT, encoding='utf-8')
            outputs = set()
            for seed in ('0', '1', '2', '3', '4', '5'):
                result = subprocess.run([sys.executable, str(script), str(project), str(root_dir)],
                                        capture_output=True, text=True, timeout=120,
                                        env={**os.environ, 'PYTHONHASHSEED': seed})
                self.assertEqual(result.returncode, 0, result.stderr)
                outputs.add(result.stdout)
        self.assertEqual(len(outputs), 1, f'{len(outputs)} different call graphs for 6 hash seeds')

class JarvisAdapterTests(Helpers, unittest.TestCase):
    def test_builtin_type_notation(self):
        self.assertEqual(jarvis_name('<**PyStr**>.join', False), '<str>.join')
        self.assertEqual(jarvis_name('<**PyDict**>.items', False), '<map>.items')
        self.assertEqual(jarvis_name('<builtin>.len', False), '<builtin>.len')
        self.assertIsNone(jarvis_name('os.path.join', False))
        self.assertEqual(jarvis_name('os.path.join', True), 'os.path.join')

    def test_class_body_convention_renames_only_the_caller(self):
        source = '''
            class Body:
                X = sorted([3, 1])
            '''
        self.assertIn('<builtin>.sorted', self.calls(source, 'app'))
        self.assertIn('<builtin>.sorted', self.calls(source, 'app.Body', conventions=('class_body',)))
        self.assertNotIn('app', knitcode_cg(*self.analyze({'app.py': source}), conventions=('class_body',)))

    def test_import_convention_resolves_relative_imports(self):
        data, graph = self.analyze({
            'pkg/__init__.py': 'from . import sub\n',
            'pkg/sub.py': 'from .util import f\nimport os\n',
            'pkg/util.py': 'def f():\n    pass\n'})
        cg = knitcode_cg(data, graph, conventions=('imports',))
        self.assertIn('pkg.sub', cg['pkg'])
        self.assertEqual(cg['pkg.sub'], ['pkg.util'])

    def test_gen_table_score_counts_like_the_artifact(self):
        truth = {'main': ['a', 'b'], 'a': []}
        self.assertEqual(gen_table_score(truth, {'main': ['a', 'c'], 'x': ['y']}),
                         dict(tp=1, fp=2, fn=1, edges=2, precision=0.3333, recall=0.5))


if __name__ == '__main__':
    unittest.main()

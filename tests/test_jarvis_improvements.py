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

    def test_decorator_call_expression_is_not_applied_twice(self):
        data, graph = self.analyze({'app.py': '''
            def factory(x):
                def dec(f):
                    return f
                return dec
            @factory(1)
            def func():
                pass
            '''})
        decorator_edges = [e for e in graph['implicit_edges'] if e['evidence']['implicit_kind'] == 'decorator']
        self.assertEqual(decorator_edges, [])

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

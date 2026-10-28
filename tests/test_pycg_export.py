"""The benchmark adapter must retain implicit edges only in its explicit opt-in view."""
from pathlib import Path
import tempfile
import unittest

from ast_parser import scan_repository
from symbol_builder import build_symbol_result
from graph_builder import build_graph
from call_status import annotate_call_statuses
from unresolved_classifier import reclassify_graph
from pycg_benchmark import to_pycg


class PyCGExportTests(unittest.TestCase):
    def test_nested_scope_is_normalized_for_calls_and_lambdas(self):
        symbols = {'symbols': [dict(kind='LAMBDA', file='app.py', line=3, column=0,
                                    canonical_name='app.outer.<locals>.<lambda>')]}
        names = ['app.outer.<locals>.inner', 'app.Error.__init__', 'app.outer.<locals>.<lambda>']
        graph = dict(nodes=[dict(id=n, canonical_name=n, name=n.split('.')[-1], kind='FUNCTION') for n in names],
                     edges=[dict(source=names[0], target=names[1], type='CALLS', evidence={}),
                            dict(source=names[0], target=names[2], type='CALLS', evidence={})])
        pairs, _, _ = to_pycg(symbols, graph)
        self.assertIn(('app.outer.inner', 'app.Error.__init__'), pairs)
        self.assertIn(('app.outer.inner', 'app.outer.<lambda1>'), pairs)

    def test_property_edge_is_separate_and_lambda_names_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'app.py').write_text(
                'class Box:\n    @property\n    def size(self): return 1\n'
                'def use():\n    box=Box()\n    return box.size\n'
                'f=lambda: len([])\nf()\n')
            symbols = build_symbol_result(scan_repository(root, source_roots=['.']))
            graph = annotate_call_statuses(reclassify_graph(build_graph(symbols), symbols), symbols)
            explicit, external, _ = to_pycg(symbols, graph)
            with_implicit, _, _ = to_pycg(symbols, graph, include_implicit=True)
            edge = ('app.use', 'app.Box.size')
            self.assertNotIn(edge, explicit)
            self.assertIn(edge, with_implicit)
            self.assertLessEqual(explicit, with_implicit)
            self.assertIn(('app', 'app.<lambda1>'), explicit)
            self.assertIn(('app.<lambda1>', '<builtin>.len'), external)

"""Behavioral contracts for the three-author bridge and prediction policy."""
import json
from pathlib import Path
import tempfile
import unittest

from ast_parser import scan_repository
from symbol_builder import build_symbol_result
from graph_builder import build_graph
from call_status import annotate_call_statuses
from unresolved_classifier import reclassify_graph
from ljy_integration import selected_supplemental_edges, write_legacy_outputs
from vscode_export import export_project


class LJYIntegrationTests(unittest.TestCase):
    def analyze(self, source, extra=None, profile='integrated', policy='supported'):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'project'; root.mkdir()
            for name, text in {'app.py': source, **(extra or {})}.items():
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            symbols = build_symbol_result(scan_repository(root))
            graph = annotate_call_statuses(reclassify_graph(
                build_graph(symbols, profile=profile, call_policy=policy), symbols), symbols)
        return graph, symbols

    def pairs(self, graph, selected=True):
        names = {n['id']: n['canonical_name'] for n in [*graph['nodes'], *graph.get('supplemental_nodes', [])]}
        edges = [*graph['edges'], *graph.get('implicit_edges', []),
                 *(selected_supplemental_edges(graph) if selected else graph['supplemental_edges'])]
        return {(names[e['source']], names[e['target']], e['type']) for e in edges}

    def test_typed_container_missing_from_primary_is_available_and_selected(self):
        source = ('class Item:\n    def run(self): pass\nclass Box:\n    items: list[Item]\n'
                  'def go(box:Box):\n    for item in box.items: item.run()\n')
        g, _ = self.analyze(source)
        self.assertIn(('app.go', 'app.Item.run', 'CALLS'), self.pairs(g))
        self.assertEqual(next(c for c in g['call_statuses'] if c['callee_text']=='item.run')['status'], 'RESOLVED_INTERNAL')

    def test_truth_and_reference_preserved_without_counting_reference_as_call(self):
        source = ('import threading\nclass Flag:\n    def __bool__(self): return True\n'
                  'def work(): pass\ndef go(flag:Flag):\n    if flag: pass\n'
                  '    threading.Thread(target=work)\n')
        g, _ = self.analyze(source)
        self.assertIn(('app.go', 'app.Flag.__bool__', 'CALLS_IMPLICIT'), self.pairs(g))
        self.assertIn(('app.go', 'app.work', 'REFERENCES'), self.pairs(g, selected=False))
        self.assertNotIn(('app.go', 'app.work', 'CALLS'), self.pairs(g))

    def test_override_candidates_preserved_but_do_not_replace_primary_dispatch(self):
        g, _ = self.analyze('class Base:\n    def run(self): pass\nclass Child(Base):\n'
                            '    def run(self): pass\ndef go(obj:Base): obj.run()\n')
        edge = ('app.go', 'app.Child.run', 'CALLS_OVERRIDE')
        self.assertIn(edge, self.pairs(g, selected=False))
        self.assertIn(edge, self.pairs(g))
        self.assertTrue(any(e['type']=='OVERRIDDEN_BY' for e in g['edges']))

    def test_concrete_base_allocation_does_not_invoke_arbitrary_child(self):
        g, _ = self.analyze('class Base:\n    def run(self): pass\nclass Child(Base):\n'
                            '    def run(self): pass\ndef go():\n    obj=Base()\n    obj.run()\n')
        self.assertNotIn(('app.go', 'app.Child.run', 'CALLS_OVERRIDE'), self.pairs(g))

    def test_primary_edges_statuses_and_patch_barriers_stay_unchanged(self):
        source = ('class Box:\n    def run(self): pass\nBox.run=unknown\n'
                  'def go(): Box().run()\n')
        g, _ = self.analyze(source)
        baseline, _ = self.analyze(source, profile='baseline')
        self.assertEqual(g['edges'], baseline['edges'])
        self.assertEqual(g['call_statuses'], baseline['call_statuses'])
        self.assertNotIn(('app.go', 'app.Box.run', 'CALLS'), self.pairs(g, selected=False))

    def test_navigation_cycle_dynamic_markers_and_html_survive_exports(self):
        source = ('import helper\ndef go(obj,name): getattr(obj,name)()\n'
                  'if __name__=="__main__": go(helper,"work")\n')
        g, symbols = self.analyze(source, {'helper.py':'import app\ndef work(): pass\n'})
        self.assertTrue(g['entry_points']); self.assertTrue(g['reading_order']['modules'])
        self.assertTrue(g['import_cycles']); self.assertTrue(g['dynamic_calls']); self.assertTrue(g['hierarchy'])
        ids = {n['id'] for n in [*g['nodes'], *g['supplemental_nodes']]}
        self.assertTrue(all(e['source'] in ids and e['target'] in ids for e in g['supplemental_edges']))
        with tempfile.TemporaryDirectory() as tmp:
            write_legacy_outputs(g, symbols, tmp)
            raw = json.loads((Path(tmp)/'ljy_graph.json').read_text())
            self.assertTrue(raw['entry_points']); self.assertTrue(raw['import_cycles'])
            self.assertIn('knit-data', (Path(tmp)/'ljy_report.html').read_text())

    def test_src_layout_maps_to_existing_shared_nodes_and_export(self):
        source = 'from pkg.core import work\ndef go(): work()\n'
        g, _ = self.analyze(source, {'src/pkg/__init__.py':'', 'src/pkg/core.py':'def work(): pass\n'})
        self.assertFalse([n for n in g['supplemental_nodes'] if n['canonical_name']=='pkg.core.work'])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'app.py').write_text(source)
            (root/'src/pkg').mkdir(parents=True)
            (root/'src/pkg/__init__.py').write_text(''); (root/'src/pkg/core.py').write_text('def work(): pass\n')
            data=export_project(root)
            self.assertEqual(data['analysis_profile'], 'integrated')
            ids={n['id'] for n in data['nodes']}
            self.assertTrue(all(e['source'] in ids and e['target'] in ids for e in data['edges']))

    def test_original_class_namespace_error_is_not_reintroduced_by_supplements(self):
        g, _ = self.analyze('class Box:\n    def work(self): pass\n    def go(self): work()\n')
        self.assertNotIn(('app.Box.go', 'app.Box.work', 'CALLS'), self.pairs(g))

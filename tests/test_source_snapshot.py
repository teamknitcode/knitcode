"""Shared AST optimization must match disk analysis and serialized fallback."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import analyze_project
from ast_parser import scan_repository
from symbol_builder import build_symbol_result
from graph_builder import build_graph
from ljy_integration import write_legacy_outputs


class SnapshotTests(unittest.TestCase):
    def test_source_excerpt_export_splits_each_file_once(self):
        class Counted(str):
            calls = 0
            def splitlines(self, *args, **kwargs):
                self.calls += 1
                return super().splitlines(*args, **kwargs)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'project';root.mkdir()
            source='class Box:\n    def first(self): return 1\n    def second(self): return 2\n'
            (root/'app.py').write_text(source)
            symbols=build_symbol_result(scan_repository(root));graph=build_graph(symbols)
            counted=Counted(source);symbols['analysis_sources']['project/app.py']=counted
            write_legacy_outputs(graph,symbols,root/'out')
            self.assertEqual(counted.calls,1)
            html=(root/'out/ljy_report.html').read_text()
            self.assertIn('return 1',html);self.assertIn('return 2',html)

    def test_shared_asts_and_json_fallback_have_identical_predictions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'project'; root.mkdir()
            (root/'app.py').write_text('class Item:\n    def run(self): pass\ndef go(): Item().run()\n')
            facts=scan_repository(root)
            symbols=build_symbol_result(facts)
            self.assertIs(symbols.syntax_trees['project/app.py'], facts.syntax_trees['project/app.py'])
            with patch('analyze_project.analyze', side_effect=AssertionError('no second semantic engine')):
                with patch.object(Path, 'write_text', side_effect=AssertionError('must not reconstruct files')):
                    shared=build_graph(symbols)
            restored=build_symbol_result(json.loads(json.dumps(facts)))
            parsed=build_graph(restored)
            self.assertEqual(shared['edges'],parsed['edges'])
            self.assertEqual(shared['ljy_result'],parsed['ljy_result'])
            self.assertEqual(shared['supplemental_edges'],parsed['supplemental_edges'])
            self.assertEqual(shared['integration_stats'],dict(shared_ast_files=1,fallback_ast_parses=0,snapshot_file_writes=0))

    def test_native_result_matches_disk_with_packages_and_console_metadata(self):
        layouts=[{'app.py':'def go(): pass\n'},
                 {'src/pkg/__init__.py':'', 'src/pkg/app.py':'def go(): pass\n'},
                 {'__init__.py':'', 'app.py':'def go(): pass\n'}]
        for files in layouts:
            with self.subTest(files=list(files)),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)/'project';root.mkdir()
                for name,text in files.items():
                    path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
                symbols=build_symbol_result(scan_repository(root))
                g=build_graph(symbols)
                self.assertEqual(g['ljy_result']['nodes'],build_graph(build_symbol_result(json.loads(json.dumps(scan_repository(root)))))['ljy_result']['nodes'])
                self.assertFalse(g['integration_contract']['legacy_analyzer_executed'])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'project';root.mkdir()
            (root/'app.py').write_text('def go(): pass\n')
            (root/'pyproject.toml').write_text('[project.scripts]\nhello="app:go"\n')
            facts=scan_repository(root)
            live=build_graph(build_symbol_result(facts))['ljy_result']
            self.assertTrue(any(e['kind']=='console_script' for e in live['entry_points']))
            restored=build_graph(build_symbol_result(json.loads(json.dumps(facts))))['ljy_result']
            self.assertEqual(live,restored)
            self.assertTrue(all(e['id'] in {n['id'] for n in live['nodes']} for e in live['entry_points']))

"""Native feature preservation and architecture checks for engine unification."""
import ast
import json
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ast_parser import scan_repository
from symbol_builder import build_symbol_result
from graph_builder import build_graph, Resolver
from object_flow import ObjectFlow
from tests import test_ljy_integration as integration


class SingleEngineTests(unittest.TestCase):
    def analyze(self, source, extra=None):
        return integration.LJYIntegrationTests().analyze(source, extra)

    @staticmethod
    def calls(graph):
        names={n['id']:n['canonical_name'] for n in graph['nodes']}
        return {(names[e['source']],names[e['target']]) for e in graph['edges']+graph['implicit_edges']
                if e['type'] in ('CALLS','CALLS_IMPLICIT')}

    def test_one_resolver_and_interpreter_without_legacy_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'app.py').write_text('class Item:\n    def run(self): pass\ndef go(): Item().run()\n')
            symbols=build_symbol_result(scan_repository(root))
            original=Resolver.build
            builds=[];runs=[]
            run=ObjectFlow.run
            def build(instance):
                builds.append(instance)
                return original(instance)
            def interpret(instance):
                runs.append(instance)
                return run(instance)
            with patch.dict(sys.modules,{'analyze_project':None}),patch.object(Resolver,'build',build),patch.object(ObjectFlow,'run',interpret):
                graph=build_graph(symbols)
            self.assertEqual(len(builds),1);self.assertEqual(len(runs),1)
            self.assertIs(runs[0].modules[next(iter(symbols.syntax_trees))],next(iter(symbols.syntax_trees.values())))
            self.assertFalse(graph['integration_contract']['legacy_analyzer_executed'])
            self.assertTrue(all(e['source'] in builds[0].by_id or e['source'].startswith('MODULE:') for e in graph['supplemental_edges']))
            self.assertFalse(graph['supplemental_nodes'])

    def test_serialized_snapshot_parses_each_source_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source='def work(): pass\n';(root/'app.py').write_text(source)
            symbols=json.loads(json.dumps(build_symbol_result(scan_repository(root))))
            original=ast.parse;reads=[]
            def parse(text,*args,**kwargs):
                if text==source:reads.append(text)
                return original(text,*args,**kwargs)
            with patch('ast.parse',side_effect=parse):build_graph(symbols)
            self.assertEqual(len(reads),1)

    def test_typed_fields_mapping_sequence_optional_and_live_write(self):
        source='''from typing import Optional
class Item:
    def run(self): pass
class Box:
    def __init__(self):
        self.items: list[Item] = []
        self.values: dict[str, Item] = {}
def go(box: Box):
    for item in box.items: item.run()
    box.values.get('a').run()
    box.values['a'].run()
    for item in box.values.values(): item.run()
def maybe(item: Optional[Item]): item.run()
def replaced(box: Box):
    box.items = []
    for item in box.items: item.run()
'''
        g,_=self.analyze(source);pairs=self.calls(g)
        self.assertIn(('app.go','app.Item.run'),pairs)
        self.assertIn(('app.maybe','app.Item.run'),pairs)
        self.assertNotIn(('app.replaced','app.Item.run'),pairs)
        run_sites=[s for s in g['call_statuses'] if s['callee_text'].endswith('.run') and s['caller_id']=='FUNCTION:app.go']
        self.assertEqual(len(run_sites),4)
        self.assertTrue(all(s['status']=='RESOLVED_INTERNAL' for s in run_sites))

    def test_truth_protocols_per_receiver_assert_and_short_circuit(self):
        g,_=self.analyze('''class Flag:
    def __bool__(self): return True
class Sized:
    def __len__(self): return 1
def go(x: Flag | Sized):
    assert x
    if not x: pass
    if False and x: pass
def dead(x: Flag):
    False and x
''')
        pairs=self.calls(g)
        self.assertIn(('app.go','app.Flag.__bool__'),pairs)
        self.assertIn(('app.go','app.Sized.__len__'),pairs)
        self.assertNotIn(('app.dead','app.Flag.__bool__'),pairs)

    def test_web_cli_entries_reexports_and_shadowed_framework(self):
        source='''from flask import Flask
from flask.views import MethodView
from typer import Typer
import click
app = Flask(__name__)
cli = Typer()
@app.get('/items')
def items(): pass
@cli.command()
def hello(): pass
class View(MethodView):
    def get(self): pass
def factory():
    local = Flask(__name__)
    @local.route('/local')
    def nested(): pass
    return local
def shadow(Flask):
    fake = Flask()
    @fake.route('/fake')
    def wrong(): pass
'''
        g,_=self.analyze(source,{'pkg/__init__.py':'from .core import public\n','pkg/core.py':'def public(): pass\n'})
        names={n['id']:n['canonical_name'] for n in g['nodes']}
        entries={(names[e['id']],e['kind']) for e in g['entry_points']}
        for pair in [('app.items','route'),('app.hello','cli_command'),('app.View.get','route'),('app.factory.nested','route')]:
            self.assertIn(pair,entries)
        self.assertNotIn(('app.shadow.wrong','route'),entries)
        self.assertIn(('pkg.core.public','public_api'),entries)

    def test_import_scope_cycle_and_dynamic_shadow(self):
        g,_=self.analyze('''from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import helper
def go(obj,name): return getattr(obj,name)
def shadow(getattr,obj,name): return getattr(obj,name)
''',{'helper.py':'import app\n'})
        self.assertEqual(g['import_cycles'][0]['kind'],'type_only')
        names={n['id']:n['canonical_name'] for n in g['nodes']}
        self.assertEqual({names[d['from']] for d in g['dynamic_calls']},{'app.go'})

    def test_reference_in_one_line_function_uses_body_owner(self):
        g,_=self.analyze('def work(): pass\ndef go(): return work\n')
        refs=[e for e in g['supplemental_edges'] if e['type']=='REFERENCES']
        self.assertEqual([(e['source'],e['target']) for e in refs],[('FUNCTION:app.go','FUNCTION:app.work')])
        self.assertNotIn(('app.go','app.work'),self.calls(g))

    def test_compatibility_view_contains_final_external_statuses_and_shared_targets(self):
        g,symbols=self.analyze('import os\ndef go():\n    print(os.getcwd())\n')
        native=g['ljy_result']
        self.assertEqual(len(native['external_edges']),2)
        self.assertEqual({e['from'] for e in native['external_edges']},{'app.py::go'})
        self.assertEqual(native['summary']['classification_source'],'unified call_statuses; static origins only')
        ids={n['id'] for n in native['nodes']}
        self.assertTrue(all(e['from'] in ids and e['to'] in ids for e in native['edges']))

    def test_class_factory_values_and_mutation_barrier(self):
        source="""class Config:
    def __init__(self): pass
class Base:
    factory = Config
    def create(self): return self.factory()
class Patched:
    factory = Config
    def create(self): return self.factory()
Patched.factory = unknown
"""
        g,_=self.analyze(source)
        self.assertIn(('app.Base.create','app.Config.__init__'),self.calls(g))
        self.assertNotIn(('app.Patched.create','app.Config.__init__'),self.calls(g))

    def test_advisory_return_does_not_overwrite_concrete_none(self):
        g,_=self.analyze('from typing import Optional\nclass Item:\n    def run(self): pass\ndef factory() -> Optional[Item]: return None\ndef go(): factory().run()\n')
        self.assertNotIn(('app.go','app.Item.run'),self.calls(g))
        self.assertTrue(any(e['source']=='FUNCTION:app.go' and e['target']=='METHOD:app.Item.run'
                            and e['evidence']['certainty']=='declared_return_advisory_may_call'
                            for e in g['supplemental_edges']))

    def test_selected_calls_in_original_feature_fixtures_are_preserved(self):
        from pycg_adapter import to_pycg
        expected=json.loads((Path(__file__).parent/'single_engine_expected_calls.json').read_text())
        expected_refs=json.loads((Path(__file__).parent/'single_engine_expected_references.json').read_text())
        for name,pairs in expected.items():
            with self.subTest(project=name):
                root=Path(__file__).parent/'ljy_original/fixtures'/name
                symbols=build_symbol_result(scan_repository(root,source_roots=['.']))
                graph=build_graph(symbols)
                actual,_,_=to_pycg(symbols,graph,include_implicit=True)
                self.assertLessEqual(set(map(tuple,pairs)),actual)
                names={n['id']:n['canonical_name'].replace('.<locals>.','.') for n in graph['nodes']}
                references={(names[e['source']],names[e['target']]) for e in graph['supplemental_edges'] if e['type']=='REFERENCES'}
                self.assertLessEqual(set(map(tuple,expected_refs[name])),references)
                if name=='graph_project':
                    names={n['id']:n['canonical_name'] for n in graph['nodes']}
                    entries={(names[e['id']],e['kind']) for e in graph['entry_points']}
                    self.assertIn(('pkg.cli.main','main_call'),entries)
                    self.assertNotIn(('tests.test_things.NotATest.test_c','test'),entries)
                if name=='classvalue_project':
                    self.assertNotIn(('tpkg.use.ambiguous','tpkg.app.App.run'),actual)

    def test_bound_callback_and_decorator_references(self):
        g,_=self.analyze("""import threading
class Resource:
    def helper(self): pass
    def start(self): threading.Thread(target=self.helper)
def deco(fn):
    def wrapper(): return fn()
    return wrapper
@deco
def decorated(): pass
""")
        names={n['id']:n['canonical_name'] for n in g['nodes']}
        refs={(names[e['source']],names[e['target']]) for e in g['supplemental_edges'] if e['type']=='REFERENCES'}
        self.assertIn(('app.Resource.start','app.Resource.helper'),refs)
        self.assertIn(('app.decorated','app.deco'),refs)
        self.assertIn(('app.deco','app.deco.wrapper'),refs)
        self.assertNotIn(('app.Resource.start','app.Resource.helper'),self.calls(g))

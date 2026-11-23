"""value_flow: inferred types of parameters, returns and call-site arguments.

A mismatch is reported only when every observed value is known and one of
them definitely does not fit a fully resolved annotation. Each warning case
has a counterpart that must stay silent.
"""
import tempfile
import textwrap
import unittest
from pathlib import Path

from ast_parser import scan_repository
from symbol_builder import build_symbol_result
from graph_builder import build_graph


def value_flow(files):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'repo'
        root.mkdir()
        for name, source in files.items():
            (root / name).write_text(textwrap.dedent(source), encoding='utf-8')
        data = build_symbol_result(scan_repository(root))
    return build_graph(data)['value_flow']


def types(entry):
    return sorted(item.get('type') for item in entry['inferred'])


def argument(flow, target, parameter):
    found = [a for c in flow['call_sites'] if c['targets'] == [target]
             for a in c['arguments'] if a['parameter'] == parameter]
    assert len(found) == 1, found
    return found[0]


class ValueFlowTests(unittest.TestCase):
    def test_schema(self):
        flow = value_flow({'app.py': 'def f():\n    return 1\nf()\n'})
        self.assertEqual(flow['schema_version'], 1)
        self.assertEqual(set(flow), {'schema_version', 'functions', 'call_sites'})

    def test_wrong_class_is_reported_at_parameter_and_call_site(self):
        flow = value_flow({'app.py': '''
            class Worker:
                def work(self): pass
            class Box:
                def work(self): pass
            def run(w: Worker, label="job"):
                w.work()
                return label
            def main():
                run(Box(), "first")
                return Box()
        '''})
        run = flow['functions']['FUNCTION:app.run']
        self.assertEqual(types(run['parameters']['w']), ['app.Box'])
        self.assertTrue(run['parameters']['w']['mismatch'])
        self.assertEqual(run['parameters']['w']['mismatch_detail'], 'declared app.Worker, received app.Box')
        self.assertEqual(types(run['parameters']['label']), ['str'])
        self.assertEqual(types(run['returns']), ['str'])
        self.assertEqual(types(flow['functions']['FUNCTION:app.main']['returns']), ['app.Box'])
        arg = argument(flow, 'FUNCTION:app.run', 'w')
        self.assertEqual(arg['text'], 'Box()')
        self.assertTrue(arg['mismatch'])

    def test_subclass_fits(self):
        flow = value_flow({'app.py': '''
            class Worker: pass
            class Fast(Worker): pass
            def run(w: Worker):
                return w
            run(Fast())
        '''})
        w = flow['functions']['FUNCTION:app.run']['parameters']['w']
        self.assertEqual(types(w), ['app.Fast'])
        self.assertFalse(w['mismatch'])

    def test_unknown_value_is_never_judged(self):
        flow = value_flow({'app.py': '''
            import json
            class Worker: pass
            def run(w: Worker):
                return w
            run(json.loads("1"))
        '''})
        w = flow['functions']['FUNCTION:app.run']['parameters']['w']
        self.assertFalse(w['mismatch'])

    def test_builtin_literals_optional_and_numeric_tower(self):
        flow = value_flow({'app.py': '''
            from typing import Optional
            def scale(x: float, limit: Optional[int] = None, name: "int | None" = None):
                return x
            scale(2)
            scale(2.5, None)
            scale(1, name="oops")
        '''})
        params = flow['functions']['FUNCTION:app.scale']['parameters']
        self.assertEqual(types(params['x']), ['float', 'int'])
        self.assertFalse(params['x']['mismatch'])        # int is accepted for float
        self.assertFalse(params['limit']['mismatch'])    # None fits Optional[int]
        self.assertTrue(params['name']['mismatch'])      # str does not fit int | None
        self.assertIn('received str', params['name']['mismatch_detail'])

    def test_typed_dict_return_is_not_judged(self):
        flow = value_flow({'app.py': '''
            import typing as t
            class Info(t.TypedDict):
                name: str
            class Plain:
                pass
            def info() -> Info:
                return {"name": "x"}
            def plain() -> Plain:
                return {"name": "x"}
            info()
            plain()
        '''})
        self.assertFalse(flow['functions']['FUNCTION:app.info']['returns']['mismatch'])
        self.assertTrue(flow['functions']['FUNCTION:app.plain']['returns']['mismatch'])

    def test_unbound_method_call_maps_self_explicitly(self):
        flow = value_flow({'app.py': '''
            class Context: pass
            class Base:
                def get(self, ctx: Context, name: str):
                    return name
            class Child(Base):
                def get(self, ctx: Context, name: str):
                    return Base.get(self, ctx, name)
            Child().get(Context(), "n")
        '''})
        site = [c for c in flow['call_sites'] if c['targets'] == ['METHOD:app.Base.get']]
        self.assertEqual(len(site), 1)
        params = [a['parameter'] for a in site[0]['arguments']]
        self.assertEqual(params, ['self', 'ctx', 'name'])
        self.assertFalse(any(a['mismatch'] for a in site[0]['arguments']))
        bound = argument(flow, 'METHOD:app.Child.get', 'ctx')
        self.assertEqual(bound['position'], 0)
        self.assertFalse(bound['mismatch'])

    def test_constructor_arguments_map_to_init(self):
        flow = value_flow({'app.py': '''
            class Port:
                def __init__(self, number: int):
                    self.number = number
            Port("80")
        '''})
        arg = argument(flow, 'METHOD:app.Port.__init__', 'number')
        self.assertTrue(arg['mismatch'])
        
    def test_rebound_builtin_name_is_not_judged(self):
        for header in ('str = bytes\n', 'from os import PathLike as str\n'):
            flow = value_flow({'app.py': header + 'def read(x: str):\n    return x\nread(b"ok")\n'})
            x = flow['functions']['FUNCTION:app.read']['parameters']['x']
            self.assertEqual(x['declared_types'], [])
            self.assertFalse(x['mismatch'])
        # A rebinding inside another function does not change the module's `str`.
        flow = value_flow({'app.py': 'def g():\n    str = 1\ndef read(x: str):\n    return x\nread(b"ok")\n'})
        self.assertTrue(flow['functions']['FUNCTION:app.read']['parameters']['x']['mismatch'])


class VSCodeExportTests(unittest.TestCase):
    def test_export_carries_value_flow_linked_to_edges(self):
        from vscode_export import export_project
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'repo'
            root.mkdir()
            (root / 'app.py').write_text('def run(x: int):\n    return x\nrun("a")\n', encoding='utf-8')
            data = export_project(root)
        flow = data['value_flow']
        self.assertEqual(flow['schema_version'], 1)
        edge_calls = {e.get('evidence', {}).get('call_id') for e in data['edges'] if e['type'] == 'calls'}
        self.assertTrue(flow['call_sites'])
        self.assertTrue(all(c['call_id'] in edge_calls for c in flow['call_sites']))
        self.assertIn('FUNCTION:app.run', {n['id'] for n in data['nodes']})
        self.assertTrue(flow['functions']['FUNCTION:app.run']['parameters']['x']['mismatch'])


if __name__ == '__main__':
    unittest.main()

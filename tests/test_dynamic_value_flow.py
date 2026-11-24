"""Exercise both public sidecar paths and verify that the original inputs survive byte-for-byte."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

from ast_parser import scan_repository
from graph_builder import build_graph
from symbol_builder import build_symbol_result, save_json

REPO = Path(__file__).resolve().parents[1]


class DynamicValueFlowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.project = self.base / 'project'
        self.project.mkdir()
        self.static = self.base / 'static'

    def prepare(self, source):
        (self.project / 'app.py').write_text(textwrap.dedent(source), encoding='utf-8')
        symbols = build_symbol_result(scan_repository(self.project))
        graph = build_graph(symbols)
        save_json(graph, self.static / 'graph_result.json')
        save_json(symbols, self.static / 'symbol_result.json')
        return graph

    def cli(self, *args, name='flow.json', status=0):
        out = self.base / name
        result = subprocess.run([sys.executable, str(REPO / 'dynamic_value_flow.py'),
                                 '--static-dir', str(self.static), '--out', str(out), *map(str, args)],
                                capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(out.read_text(encoding='utf-8'))['dynamic_value_flow']

    def capture(self, **kwargs):
        return self.cli('--project', self.project, '--script', 'app.py', **kwargs)

    def snapshot(self):
        return {p: p.read_bytes() for p in self.static.iterdir()}

    def test_example_and_input_preservation(self):
        graph = self.prepare((REPO / 'examples/dynamic_value_flow/app.py').read_text(encoding='utf-8'))
        before = self.snapshot()
        flow = self.capture()
        self.assertTrue(flow['trace_complete'])
        self.assertEqual(before, self.snapshot())
        func = flow['functions']['FUNCTION:app.run']
        w = func['parameters']['w']
        self.assertEqual(w['declared_types'], ['app.Worker'])
        self.assertEqual([t['type'] for t in w['inferred']], ['app.Box', 'app.Worker'])
        self.assertTrue(w['mismatch'])
        self.assertEqual(func['returns']['inferred'], [{'kind': 'builtin', 'type': 'str'}])
        sites = [s for s in flow['call_sites'] if s['targets'] == ['FUNCTION:app.run']]
        self.assertEqual(len(sites), 2)
        ids = {e.get('evidence', {}).get('call_id') for e in graph['edges']}
        self.assertTrue(all(s['call_id'] in ids for s in sites))
        args = {s['arguments'][0]['text']: s['arguments'][0] for s in sites}
        self.assertFalse(args['Worker()']['mismatch'])
        self.assertEqual(args['Box()']['mismatch_detail'], 'declared app.Worker, received app.Box')
        # Retrying against an existing output must leave it intact.
        original = (self.base / 'flow.json').read_bytes()
        self.capture(status=1)
        self.assertEqual(original, (self.base / 'flow.json').read_bytes())

    def test_same_line_multiline_defaults_methods_and_unpack(self):
        self.prepare("""
            class Service:
                def choose(self, x: int = 0, *, name: str = ''): return x
            s = Service()
            s.choose(1); s.choose("bad")
            Service.choose(
                s, 3, name="ok")
            s.choose(*[4])
        """)
        flow = self.capture()
        sites = [s for s in flow['call_sites'] if s['targets'] == ['METHOD:app.Service.choose']]
        self.assertEqual(len(sites), 4)
        self.assertEqual(len({s['call_id'] for s in sites}), 4)
        args = {a['text']: a for s in sites for a in s['arguments']}
        self.assertEqual(args['1']['inferred'], [{'kind': 'builtin', 'type': 'int'}])
        self.assertTrue(args["'bad'"]['mismatch'])
        self.assertEqual(args['s']['parameter'], 'self')
        self.assertEqual(args["'ok'"]['keyword'], 'name')
        self.assertTrue(args['*[4]']['unknown'])
        self.assertFalse(args['*[4]']['mismatch'])

    def test_legacy_trace_and_ambiguous_call_ids(self):
        self.prepare("""
            def run(x: int): return x
            run(1); run("bad")
            run(2)
        """)
        trace = self.base / 'trace.json'
        subprocess.run([sys.executable, str(REPO / 'dynamic_analysis.py'), 'record', str(self.project),
                        '--script', 'app.py', '--out', str(trace), '--calls-only', '--no-children'],
                       capture_output=True, check=True, timeout=40)
        hybrid = self.base / 'hybrid.json'
        subprocess.run([sys.executable, str(REPO / 'dynamic_analysis.py'), 'compare',
                        '--static-dir', str(self.static), '--trace', str(trace), '--out', str(hybrid)],
                       capture_output=True, check=True, timeout=40)
        before = {p: p.read_bytes() for p in [*self.static.iterdir(), trace, hybrid]}
        flow = self.cli('--trace', trace)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertTrue(flow['functions']['FUNCTION:app.run']['parameters']['x']['mismatch'])
        self.assertEqual(len(flow['call_sites']), 1)
        arg = flow['call_sites'][0]['arguments'][0]
        self.assertTrue(arg['unknown'])
        self.assertFalse(arg['mismatch'])
        self.assertEqual(len(flow['unlinked_calls']), 2)

    def test_source_mismatch_and_partial_execution(self):
        self.prepare("def fails(x: str) -> str:\n    raise ValueError(x)\nfails(1)\n")
        flow = self.capture(status=1)
        self.assertFalse(flow['trace_complete'])
        ret = flow['functions']['FUNCTION:app.fails']['returns']
        self.assertTrue(ret['unknown'])
        self.assertFalse(ret['mismatch'])
        (self.project / 'app.py').write_text('def fails(): return 3\nfails()\n', encoding='utf-8')
        changed = self.capture(name='changed.json')
        self.assertEqual(changed['file_verification']['app.py'], 'source_mismatch')
        self.assertFalse(changed['functions'])
        self.assertFalse(changed['call_sites'])
        self.assertTrue(changed['unmapped_functions'])

    def test_conservative_typing_and_generator(self):
        self.prepare("""
            from typing import Any, Optional, Protocol, TypedDict
            class W: pass
            class Child(W): pass
            class Info(TypedDict): label: str
            class P(Protocol): pass
            def f(w: W, n: float, opt: Optional[int], a: Any, p: P, i: Info):
                return w
            f(Child(), 2, None, 1, Child(), {})
            def values():
                yield 2
                return 'done'
            list(values())
            def never(x: int): pass
        """)
        flow = self.capture()
        self.assertFalse(any(v['mismatch'] for v in flow['functions']['FUNCTION:app.f']['parameters'].values()))
        self.assertNotIn('FUNCTION:app.never', flow['functions'])
        g = flow['functions']['FUNCTION:app.values']
        self.assertEqual(g['yields']['inferred'][0]['type'], 'int')
        self.assertEqual(g['returns']['inferred'][0]['type'], 'str')

    def test_extension_copy_preserves_original_fields(self):
        from vscode_export import export_project
        self.prepare('def f(x: int): return x\nf("wrong")\n')
        extension = export_project(self.project)
        source = self.base / 'vscode.json'
        save_json(extension, source)
        original = source.read_bytes()
        flow = self.cli('--vscode-data', source, '--project', self.project, '--script', 'app.py')
        copy = json.loads((self.base / 'flow.json').read_text(encoding='utf-8'))
        self.assertEqual(copy.pop('dynamic_value_flow'), flow)
        self.assertEqual(copy, extension)
        self.assertEqual(source.read_bytes(), original)
        self.assertTrue(flow['call_sites'][0]['arguments'][0]['mismatch'])

    def test_dynamic_only_calls_and_module_arguments(self):
        self.prepare("""
            import sys
            class Service:
                def run(self, value: int): return value
            def main():
                getattr(Service(), sys.argv[1])(sys.argv[2])
            main()
        """)
        flow = self.cli('--project', self.project, '--module', 'app', '--', 'run', 'wrong')
        self.assertTrue(flow['trace_complete'])
        param = flow['functions']['METHOD:app.Service.run']['parameters']['value']
        self.assertTrue(param['mismatch'])
        edge = next(e for e in flow['unlinked_calls'] if e['target'] == 'METHOD:app.Service.run')
        self.assertIsNone(edge['call_id'])
        self.assertIn('sys.argv[2]', edge['text'])
        self.assertTrue(edge['source_call_id'].startswith('CALL:'))
        self.assertEqual(edge['bound_parameter_types']['value'], ['builtins.str'])

    def test_variadic_and_coroutine_returns(self):
        self.prepare("""
            def collect(*args: int, **kwargs: str): pass
            collect(1, name="ok")
            async def task() -> int: return "wrong"
            coro = task()
            try: coro.send(None)
            except StopIteration: pass
        """)
        flow = self.capture()
        params = flow['functions']['FUNCTION:app.collect']['parameters']
        self.assertEqual(params['args']['declared'], 'int')
        self.assertEqual(params['kwargs']['inferred'][0]['type'], 'dict')
        self.assertFalse(any(p['mismatch'] for p in params.values()))
        task = flow['functions']['FUNCTION:app.task']
        self.assertEqual(task['execution_kind'], 'coroutine')
        self.assertTrue(task['returns']['mismatch'])

    def test_alias_and_forwarded_arguments(self):
        self.prepare("""
            from functools import partial
            def run(x: int, label: str): pass
            alias = run
            alias(1, 'right')
            run = partial(run, 2)
            run('second')
        """)
        flow = self.capture()
        sites = [s for s in flow['call_sites'] if s['targets'] == ['FUNCTION:app.run']]
        alias = next(s for s in sites if len(s['arguments']) == 2)
        self.assertEqual([a['parameter'] for a in alias['arguments']], ['x', 'label'])
        for site in sites:
            if len(site['arguments']) == 1:
                self.assertTrue(site['arguments'][0]['unknown'])
        self.assertEqual(flow['functions']['FUNCTION:app.run']['parameters']['x']['inferred'],
                         [{'kind': 'builtin', 'type': 'int'}])


if __name__ == '__main__':
    unittest.main()

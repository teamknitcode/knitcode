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
        self.assertEqual(args['Worker()']['check_status'], 'match')
        self.assertEqual(args['Box()']['check_status'], 'mismatch')
        self.assertEqual(func['parameters']['label']['check_reason'], 'no_annotation')
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

    def test_list_element_evidence_is_bounded_and_call_specific(self):
        self.prepare("""
            def batch(xs: 'list[int]'):
                xs.clear()
            def run():
                batch([1, 2]); batch([1, "wrong"])
                batch([])
                for _ in range(2):
                    batch([0] * 32 + ["outside"])
                batch(["first"] + [0] * 35)
            run()
        """)
        flow = self.capture()
        sites = [s for s in flow['call_sites'] if s['targets'] == ['FUNCTION:app.batch']]
        by_expr = {s['arguments'][0]['text']: s['arguments'][0] for s in sites}
        good, bad, empty = by_expr['[1, 2]'], by_expr["[1, 'wrong']"], by_expr['[]']
        partial = by_expr["[0] * 32 + ['outside']"]
        sampled_bad = by_expr["['first'] + [0] * 35"]
        self.assertEqual(good['check_status'], 'match')
        self.assertFalse(good['inferred'][0]['elements_unknown'])
        self.assertTrue(bad['mismatch'])
        self.assertEqual((bad['check_reason'], bad['element_check']['index'],
                          bad['element_check']['observed_type']), ('incompatible_element', 1, 'str'))
        self.assertEqual(empty['element_check']['reason'], 'empty_list')
        self.assertEqual((partial['check_status'], partial['element_check']['checked'],
                          partial['element_check']['total']), ('partial', 64, 66))
        self.assertTrue(sampled_bad['mismatch'])
        self.assertTrue(sampled_bad['inferred'][0]['elements_unknown'])
        fn = flow['functions']['FUNCTION:app.batch']['parameters']['xs']
        self.assertTrue(fn['mismatch'])
        self.assertEqual((fn['element_check']['checked'], fn['element_check']['total']), (100, 106))

    def test_legacy_lists_and_unsupported_element_annotations(self):
        self.prepare("""
            from typing import List
            def batch(xs: List[int]): pass
            def nested(xs: list[list[int]]): pass
            def words(xs: list["str"]): pass
            class Special(list):
                def __iter__(self): raise ValueError("must not iterate")
            batch([False, 1])
            batch(Special())
            nested([["wrong"]])
            words([3])
        """)
        fresh = self.capture()
        nested = fresh['functions']['FUNCTION:app.nested']['parameters']['xs']
        self.assertEqual(nested['check_status'], 'partial')
        self.assertTrue(fresh['functions']['FUNCTION:app.words']['parameters']['xs']['mismatch'])
        batch = fresh['functions']['FUNCTION:app.batch']['parameters']['xs']
        self.assertEqual(batch['element_check']['status'], 'match')
        self.assertEqual(batch['check_status'], 'partial')
        trace = self.base / 'legacy.json'
        subprocess.run([sys.executable, str(REPO / 'dynamic_analysis.py'), 'record', str(self.project),
                        '--script', 'app.py', '--out', str(trace), '--calls-only', '--no-children'],
                       capture_output=True, check=True, timeout=40)
        legacy = self.cli('--trace', trace, name='legacy-flow.json')
        fn = legacy['functions']['FUNCTION:app.batch']['parameters']['xs']
        self.assertEqual(fn['element_check'], {'status': 'unchecked', 'reason': 'elements_not_recorded'})
        self.assertFalse(fn['mismatch'])

    def test_list_checks_each_declared_element_type(self):
        self.prepare("""
            from typing import Annotated, List as L, Optional as Maybe, Union as Either
            class Worker: pass
            class Child(Worker): pass
            class Other: pass
            def accept(words: list[str], counts: list[float], flags: list[bool],
                       values: list[int | str], workers: L["Worker"], optional: list[Maybe[bytes]],
                       marked: list[Annotated[Either[str, int], "id"]], errors: list[Exception]): pass
            accept(["hi"], [1, 2.5], [False], [7, "id"], [Child()], [None, b"a"], ["id", 1], [ValueError()])
            accept(["hi", 3], ["3"], [1], [3.5], [Other()], ["a"], [b"id"], ["oops"])
        """)
        flow = self.capture()
        fn = 'FUNCTION:app.accept'
        good, bad = sorted((s for s in flow['call_sites'] if s['targets'] == [fn]), key=lambda s: s['line'])
        cases = {'words': (['str'], 'int', 1), 'counts': (['float'], 'str', 0),
                 'flags': (['bool'], 'int', 0), 'values': (['int', 'str'], 'float', 0),
                 'workers': (['app.Worker'], 'app.Other', 0), 'optional': (['NoneType', 'bytes'], 'str', 0),
                 'marked': (['int', 'str'], 'bytes', 0), 'errors': (['Exception'], 'str', 0)}
        self.assertEqual({a['parameter'] for a in good['arguments']}, cases.keys())
        for a in good['arguments']:
            with self.subTest(parameter=a['parameter'], call='valid'):
                self.assertEqual(a['check_status'], 'match')
                self.assertEqual(a['element_check']['declared_types'], cases[a['parameter']][0])
        for a in bad['arguments']:
            with self.subTest(parameter=a['parameter'], call='invalid'):
                check = a['element_check']
                self.assertEqual(a['check_status'], 'mismatch')
                self.assertEqual((check['declared_types'], check['observed_type'], check['index']),
                                 cases[a['parameter']])
                self.assertTrue(flow['functions'][fn]['parameters'][a['parameter']]['mismatch'])

    def test_list_union_with_parameterized_elements(self):
        self.prepare("""
            def batch(items: list[str | dict[str, int]]): pass
            batch(["ok"])
            batch([{"x": "unchecked"}])
            batch([False])
        """)
        flow = self.capture()
        sites = sorted((s for s in flow['call_sites'] if s['targets'] == ['FUNCTION:app.batch']),
                       key=lambda s: s['line'])
        args = [site['arguments'][0] for site in sites]
        self.assertEqual([a['check_status'] for a in args], ['match', 'partial', 'mismatch'])
        self.assertEqual(args[1]['element_check']['reason'], 'element_details_unchecked')
        self.assertEqual(args[2]['element_check']['observed_type'], 'bool')

    def test_list_unresolved_alternative_and_rebound_builtin(self):
        self.prepare("""
            from __future__ import annotations
            from builtins import Exception as Problem
            Exception = str
            def batch(declared: list[Exception], imported: list[Problem], unknown: list[int | Missing]): pass
            batch(["ok"], [ValueError()], ["undecidable"])
        """)
        params = self.capture()['functions']['FUNCTION:app.batch']['parameters']
        self.assertEqual(params['declared']['element_check']['declared_types'], ['str'])
        self.assertEqual(params['declared']['check_status'], 'match')
        self.assertEqual(params['imported']['check_status'], 'match')
        self.assertEqual(params['unknown']['check_status'], 'partial')
        self.assertFalse(params['unknown']['mismatch'])

    def test_imported_element_alias_at_declaration(self):
        self.prepare("""
            from typing import List as Element
            def before(xs: list[Element]): pass
            Element = set
            def after(xs: list[Element]): pass
            before([[1]])
            after([{1}]); after([[1]])
            if __name__ == '__main__': Element = tuple
            def uncertain(xs: list[Element]): pass
            uncertain([(1,)])
            from typing import Dict as Element
            def imported_again(xs: list[Element]): pass
            imported_again([{}])
        """)
        flow = self.capture()
        def checks(name):
            return [site['arguments'][0] for site in flow['call_sites']
                    if site['targets'] == ['FUNCTION:app.' + name]]
        self.assertEqual(checks('before')[0]['check_status'], 'match')
        after = {a['text']: a for a in checks('after')}
        self.assertEqual(after['[{1}]']['element_check']['declared_types'], ['set'])
        self.assertEqual(after['[{1}]']['check_status'], 'match')
        self.assertEqual(after['[[1]]']['element_check']['observed_type'], 'list')
        self.assertTrue(after['[[1]]']['mismatch'])
        self.assertEqual(checks('uncertain')[0]['check_status'], 'partial')
        self.assertEqual(checks('imported_again')[0]['check_status'], 'match')

    def test_forward_element_class_and_wildcard_rebinding(self):
        (self.project / 'aliases.py').write_text('int = str\n', encoding='utf-8')
        self.prepare("""
            def forward(items: list["Later"]): pass
            class Later: pass
            forward([Later()]); forward([1])
        """)
        flow = self.capture()
        calls = {s['arguments'][0]['text']: s['arguments'][0] for s in flow['call_sites']
                 if s['targets'] == ['FUNCTION:app.forward']}
        self.assertEqual(calls['[Later()]']['check_status'], 'match')
        self.assertEqual(calls['[1]']['element_check']['declared_types'], ['app.Later'])
        self.assertTrue(calls['[1]']['mismatch'])

        self.prepare("""
            from aliases import *
            from builtins import list
            def accept(items: list[int]): pass
            accept(["ok"])
            from builtins import int
            def restored(items: list[int]): pass
            restored(["wrong"])
        """)
        functions = self.capture(name='wildcard.json')['functions']
        self.assertEqual(functions['FUNCTION:app.accept']['parameters']['items']['check_status'], 'partial')
        self.assertTrue(functions['FUNCTION:app.restored']['parameters']['items']['mismatch'])

    def test_nullable_list_selects_branch_for_observed_type(self):
        self.prepare("""
            from typing import Annotated, Optional as Maybe, Union as Either
            def modern(xs: list[str] | None): pass
            def optional(xs: Maybe[list[str]]): pass
            def wrapped(xs: Annotated[Either[None, list[str]], "values"]): pass
            modern(None); modern(["ok"]); modern(["ok", 7]); modern(3)
            optional(None); optional(["ok", 7])
            wrapped(["ok", 7])
            def two_lists(xs: list[str] | list[int]): pass
            two_lists([1, "two"])
        """)
        flow = self.capture()
        calls = {(s['targets'][0].split('.')[-1], s['arguments'][0]['text']): s['arguments'][0]
                 for s in flow['call_sites'] if s['arguments']}
        for name in ('modern', 'optional', 'wrapped'):
            arg = calls[name, "['ok', 7]"]
            self.assertTrue(arg['mismatch'])
            self.assertEqual((arg['element_check']['index'], arg['element_check']['observed_type']), (1, 'int'))
            self.assertTrue(flow['functions']['FUNCTION:app.' + name]['parameters']['xs']['mismatch'])
        for name in ('modern', 'optional'):
            self.assertEqual(calls[name, 'None']['check_status'], 'match')
            self.assertNotIn('element_check', calls[name, 'None'])
        self.assertEqual(calls['modern', "['ok']"]['check_status'], 'match')
        self.assertTrue(calls['modern', '3']['mismatch'])
        self.assertEqual(calls['two_lists', "[1, 'two']"]['check_status'], 'partial')

    def test_custom_subscription_cannot_establish_element_type(self):
        self.prepare("""
            class AsInt:
                def __class_getitem__(cls, key): return int
            class Derived(AsInt): pass
            def accept(xs: list[AsInt[str]], ys: list[Derived[bytes]]): pass
            accept([1], [1])
        """)
        flow = self.capture()
        site = next(s for s in flow['call_sites'] if s['targets'] == ['FUNCTION:app.accept'])
        for arg in site['arguments']:
            self.assertEqual(arg['check_status'], 'partial')
            self.assertFalse(arg['mismatch'])
            self.assertFalse(flow['functions']['FUNCTION:app.accept']['parameters'][arg['parameter']]['mismatch'])

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
        params = flow['functions']['FUNCTION:app.f']['parameters']
        self.assertFalse(any(v['mismatch'] for v in params.values()))
        self.assertEqual(params['opt']['check_status'], 'match')
        self.assertEqual(params['a']['check_reason'], 'unrestricted_annotation')
        self.assertEqual(params['p']['check_status'], 'unchecked')
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

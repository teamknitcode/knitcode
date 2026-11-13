"""Exercise the public CLI and static bridge with real, isolated local runs."""
import contextlib
import io
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
import main as analyzer
from runtime_validation.runtime_bridge import compare

CLI = Path(__file__).resolve().parents[1] / 'dynamic_analysis.py'


class DynamicAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='knitcode-dynamic-test-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / '로컬 프로젝트'
        self.root.mkdir()
        self.trace = self.base / 'trace.json'
        self.static = self.base / 'static'

    def write(self, file, source):
        path = self.root / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source).lstrip('\n'), encoding='utf-8')
        return path

    def run_target(self, *options, status=0, args=()):
        command = [sys.executable, str(CLI), 'record', str(self.root),
                   '--out', str(self.trace), *options, '--', *args]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(self.trace.read_text(encoding='utf-8')), result

    def static_analysis(self):
        symbols = build_symbol_result(scan_repository(self.root))
        graph = build_graph(symbols)
        save_json(symbols, self.static / 'symbol_result.json')
        save_json(graph, self.static / 'graph_result.json')
        return symbols, graph

    @staticmethod
    def named_edges(trace):
        nodes = {node['id']: node for node in trace['nodes']}
        return [(nodes[e['source']]['name'], nodes[e['target']]['name'], e)
                for e in trace['edges']]

    def test_direct_recursion_dynamic_dispatch_and_counts(self):
        self.write('app.py', '''
            class Service:
                def run(self): return 1
            def recurse(n):
                if n: recurse(n - 1)
            def main():
                service = Service()
                name = ''.join(['r', 'un'])
                for _ in range(3): getattr(service, name)()
                recurse(2)
            main()
        ''')
        trace, _ = self.run_target('--script', 'app.py')
        self.assertTrue(trace['complete'])
        edges = self.named_edges(trace)
        self.assertEqual(sum(e['count'] for a, b, e in edges if (a, b) == ('main', 'run')), 3)
        self.assertEqual(sum(e['count'] for a, b, e in edges if (a, b) == ('recurse', 'recurse')), 2)
        self.assertTrue(all(n['file'] == 'app.py' for n in trace['nodes']))

    def test_arguments_cwd_imports_and_source_encoding(self):
        app = self.root / 'sub' / 'app.py'
        app.parent.mkdir()
        app.write_bytes(b'# coding: latin-1\nimport sys\nfrom helper import value\n'
                        b'assert value == "caf\xe9"\nassert sys.argv[1:] == ["--flag", "hello world"]\n'
                        b'assert open("input.txt").read() == "ok"\n')
        self.write('sub/helper.py', 'value = "café"\n')
        self.write('data/input.txt', 'ok')
        trace, _ = self.run_target('--script', 'sub/app.py', '--cwd', 'data',
                                   args=('--flag', 'hello world'))
        self.assertTrue(trace['complete'])
        self.assertIn('sub/helper.py', trace['files'])

    def test_src_package_module_and_relative_import(self):
        self.write('src/pkg/__init__.py', '')
        self.write('src/pkg/work.py', 'def work(): return 7\n')
        self.write('src/pkg/__main__.py', 'from .work import work\nassert work() == 7\n')
        trace, _ = self.run_target('--module', 'pkg')
        self.assertEqual(trace['execution']['source_roots'], ['src'])
        self.static_analysis()
        hybrid = compare(self.static, self.trace)
        self.assertTrue(any(e['target'] == 'FUNCTION:pkg.work.work' for e in hybrid['runtime_edges']))

    def test_threads_finishing_after_entry_and_atexit_are_captured(self):
        self.write('app.py', '''
            import atexit
            import threading
            import time
            def work(): pass
            def background():
                time.sleep(0.05)
                for _ in range(20): work()
            def cleanup(): work()
            atexit.register(cleanup)
            threading.Thread(target=background).start()
        ''')
        trace, _ = self.run_target('--script', 'app.py')
        edges = self.named_edges(trace)
        self.assertEqual(sum(e['count'] for a, b, e in edges if (a, b) == ('background', 'work')), 20)
        self.assertEqual(sum(e['count'] for a, b, e in edges if (a, b) == ('cleanup', 'work')), 1)
        background = next(n for n in trace['nodes'] if n['name'] == 'background')
        self.assertEqual(background['entry_events'], 1)
        self.assertFalse(any(a == '<module>' and b == 'background' for a, b, _ in edges))

    def test_main_module_stays_available_in_threads_and_exit_callbacks(self):
        self.write('app.py', '''
            import atexit
            import threading
            import time
            marker = 42
            def check():
                import __main__
                assert __main__.marker == marker
                print('main-module-ok')
            def background():
                time.sleep(0.05)
                check()
            atexit.register(check)
            threading.Thread(target=background).start()
        ''')
        trace, result = self.run_target('--script', 'app.py')
        self.assertEqual(result.stdout.count('main-module-ok'), 2)
        self.assertTrue(trace['complete'])

    def test_spawn_process_records_child_calls_with_process_provenance(self):
        self.write('app.py', '''
            from pathlib import Path
            import multiprocessing
            def child(path): Path(path).write_text('child-ok')
            if __name__ == '__main__':
                process = multiprocessing.get_context('spawn').Process(target=child, args=('child.txt',))
                process.start()
                process.join()
                assert process.exitcode == 0
                assert Path('child.txt').read_text() == 'child-ok'
        ''')
        trace, _ = self.run_target('--script', 'app.py')
        child = next(node for node in trace['nodes'] if node['name'] == 'child')
        self.assertEqual(len(trace['processes']), 2)
        self.assertNotIn(trace['pid'], child['process_ids'])
        self.assertFalse(any(e['target'] == child['id'] for e in trace['edges']))

    def test_argument_receiver_return_and_yield_types(self):
        self.write('app.py', '''
            class Base:
                def run(self, value, *, enabled=True): return value if enabled else None
                @classmethod
                def kind(cls): return cls.__name__
            class Child(Base): pass
            def stream(): yield 3
            Child().run(4)
            Child().run('text', enabled=False)
            Child.kind()
            list(stream())
        ''')
        trace, _ = self.run_target('--script', 'app.py')
        run = next(node for node in trace['nodes'] if node['name'] == 'run')
        self.assertEqual(run['receiver_types'], ['__main__.Child'])
        self.assertEqual(run['argument_types']['value'], ['builtins.int', 'builtins.str'])
        self.assertEqual(run['return_types'], ['builtins.NoneType', 'builtins.int'])
        kind = next(node for node in trace['nodes'] if node['name'] == 'kind')
        self.assertEqual(kind['receiver_types'], ['__main__.Child'])
        stream = next(node for node in trace['nodes'] if node['name'] == 'stream')
        self.assertEqual(stream['yield_types'], ['builtins.int'])

    def test_both_branch_paths_and_unexecuted_function_lines(self):
        self.write('app.py', '''
            def choose(flag):
                return 1 if flag else 2
            def unused():
                return 99
            def loop(items):
                total = 0
                for value in items:
                    if value: total += value
                return total
            choose(True)
            choose(False)
            loop([0, 1])
        ''')
        trace, _ = self.run_target('--script', 'app.py')
        file = next(file for file in trace['coverage']['files'] if file['file'] == 'app.py')
        self.assertIn(4, file['missing_lines'])
        self.assertTrue(all(not branch['missing'] for branch in file['branches']))
        self.assertTrue(all(not branch['unexpected_destinations'] for branch in file['branches']))
        self.assertEqual(trace['coverage']['summary']['branch_coverage'], 1.0)

    def test_variable_reads_writes_and_binding_flows(self):
        self.write('app.py', '''
            def transform(value):
                assigned = value
                copied = assigned
                answer = assigned + copied
                return answer
            assert transform(3) == 6
        ''')
        trace, _ = self.run_target('--script', 'app.py')
        events = trace['variables']['events']
        node = next(node for node in trace['nodes'] if node['name'] == 'transform')
        observed = {(e['name'], e['operation']) for e in events if e['node'] == node['id']}
        for variable in ('assigned', 'copied', 'answer'):
            self.assertIn((variable, 'write'), observed)
            self.assertIn((variable, 'read'), observed)
        by_id = {event['id']: event for event in events}
        self.assertTrue(any(by_id[flow['source']]['name'] == 'assigned'
                            and by_id[flow['source']]['operation'] == 'write'
                            and by_id[flow['target']]['operation'] == 'read'
                            for flow in trace['variables']['binding_flows']))

    def test_nested_subprocesses_are_collected_and_failures_are_partial(self):
        self.write('leaf.py', 'def work(): return 1\nwork()\nraise SystemExit(5)\n')
        self.write('child.py', '''
            import subprocess
            import sys
            subprocess.run([sys.executable, 'leaf.py'])
        ''')
        self.write('app.py', '''
            import subprocess
            import sys
            subprocess.run([sys.executable, 'child.py'])
        ''')
        trace, _ = self.run_target('--script', 'app.py', status=1)
        self.assertEqual(len(trace['processes']), 3)
        self.assertTrue(any(p['execution']['exit_code'] == 5 for p in trace['processes']))
        self.assertTrue(any(node['file'] == 'leaf.py' and node['name'] == 'work' for node in trace['nodes']))
        self.assertFalse(trace['complete'])

    def test_missing_child_bootstrap_is_explicitly_partial(self):
        self.write('app.py', '''
            import subprocess
            import sys
            subprocess.run([sys.executable, '-S', '-c', 'pass'], check=True)
        ''')
        trace, _ = self.run_target('--script', 'app.py', '--child-wait', '0', status=1)
        self.assertEqual(len(trace['missing_process_ids']), 1)

    def test_calls_only_and_entry_process_only_options(self):
        self.write('child.py', 'def work(): pass\nwork()\n')
        self.write('app.py', '''
            import subprocess
            import sys
            def run(): return 1
            run()
            subprocess.run([sys.executable, 'child.py'], check=True)
        ''')
        trace, _ = self.run_target('--script', 'app.py', '--calls-only', '--no-children')
        self.assertFalse(trace['coverage']['enabled'])
        self.assertFalse(trace['variables']['enabled'])
        self.assertEqual(trace['variables']['events'], [])
        self.assertEqual(len(trace['processes']), 1)
        self.assertTrue(any(node['name'] == 'run' for node in trace['nodes']))
        self.assertFalse(any(node['file'] == 'child.py' for node in trace['nodes']))

    def test_target_annotations_keep_normal_python_semantics(self):
        self.write('app.py', 'def work(value: int): pass\nassert work.__annotations__["value"] is int\n')
        trace, _ = self.run_target('--script', 'app.py')
        self.assertTrue(trace['complete'])

    def test_type_capture_avoids_custom_metaclass_properties_and_repr(self):
        self.write('app.py', '''
            class Meta(type):
                @property
                def __module__(cls): raise RuntimeError('metadata property executed')
            class Item(metaclass=Meta):
                def __repr__(self): raise RuntimeError('repr executed')
            def identity(value): return value
            identity(Item())
        ''')
        trace, _ = self.run_target('--script', 'app.py')
        node = next(node for node in trace['nodes'] if node['name'] == 'identity')
        self.assertEqual(node['argument_types']['value'], ['__main__.Item'])
        self.assertEqual(node['return_types'], ['__main__.Item'])

    def test_generator_resumption_preserves_bindings_and_initial_argument_types(self):
        self.write('app.py', '''
            def stream(value):
                value = 'changed'
                assigned = value
                yield 1
                yield assigned
            list(stream(3))
        ''')
        trace, _ = self.run_target('--script', 'app.py')
        node = next(node for node in trace['nodes'] if node['name'] == 'stream')
        self.assertEqual(node['argument_types']['value'], ['builtins.int'])
        events = {event['id']: event for event in trace['variables']['events']}
        self.assertTrue(any(events[flow['source']]['name'] == 'assigned'
                            and events[flow['target']]['line'] == 5
                            for flow in trace['variables']['binding_flows']))

    def test_external_calls_are_boundaries(self):
        self.write('app.py', 'import json\nitems = []\nitems.append(1)\njson.dumps(items)\n')
        trace, _ = self.run_target('--script', 'app.py')
        external = {(e['target'], e['kind']) for e in trace['external_calls']}
        self.assertIn(('builtins.list.append', 'native_boundary'), external)
        self.assertIn(('json.dumps', 'python_external'), external)

    def test_bridge_preserves_extended_runtime_evidence(self):
        self.write('app.py', 'def work(value): return value\nwork(1)\n')
        self.static_analysis()
        self.run_target('--script', 'app.py')
        hybrid = compare(self.static, self.trace)
        node = next(node for node in hybrid['runtime_observations'] if node['name'] == 'work')
        self.assertEqual(node['static_id'], 'FUNCTION:app.work')
        self.assertEqual(node['argument_types']['value'], ['builtins.int'])
        self.assertIsNotNone(hybrid['coverage'])
        self.assertGreater(len(hybrid['variables']['events']), 0)

    def test_source_modified_during_execution_is_detected(self):
        self.write('app.py', '''
            from pathlib import Path
            def work():
                path = Path(__file__)
                path.write_text(path.read_text() + '\\n# changed\\n')
            work()
        ''')
        self.static_analysis()
        trace, _ = self.run_target('--script', 'app.py')
        self.assertTrue(trace['files']['app.py']['changed_during_run'])
        hybrid = compare(self.static, self.trace)
        self.assertEqual(hybrid['file_verification']['app.py'], 'source_changed_during_run')

    def test_uncaught_exception_saves_partial_trace_and_exit_status(self):
        self.write('app.py', 'def fail(): raise RuntimeError("failure")\nfail()\n')
        trace, result = self.run_target('--script', 'app.py', status=1)
        self.assertFalse(trace['complete'])
        self.assertEqual(trace['execution']['exception']['type'], 'RuntimeError')
        self.assertIn('RuntimeError: failure', result.stderr)
        self.assertTrue(any(b == 'fail' for _, b, _ in self.named_edges(trace)))

    def test_system_exit_status_is_preserved(self):
        self.write('app.py', 'raise SystemExit(7)\n')
        trace, _ = self.run_target('--script', 'app.py', status=7)
        self.assertEqual(trace['execution']['exit_code'], 7)
        self.assertEqual(trace['execution']['process_exit_code'], 7)

    def test_replaced_hook_is_reported_as_partial(self):
        self.write('app.py', 'import sys\nsys.setprofile(None)\n')
        trace, _ = self.run_target('--script', 'app.py', status=1)
        self.assertFalse(trace['profile_hooks_intact'])
        self.assertFalse(trace['complete'])

    def test_background_and_atexit_errors_are_reported(self):
        self.write('app.py', '''
            import atexit
            import threading
            def fail(): raise RuntimeError('background failure')
            def cleanup(): raise ValueError('exit failure')
            atexit.register(cleanup)
            threading.Thread(target=fail).start()
        ''')
        trace, _ = self.run_target('--script', 'app.py', status=1)
        self.assertEqual(trace['execution']['thread_exceptions'][0]['type'], 'RuntimeError')
        self.assertEqual(trace['execution']['unraisable_exceptions'][0]['type'], 'ValueError')
        self.assertFalse(trace['complete'])

    def test_resumptions_and_same_line_lambdas_retain_real_scopes(self):
        self.write('app.py', '''
            import asyncio
            def helper(): return 1
            def values():
                yield helper()
                yield helper()
            async def task():
                await asyncio.sleep(0)
                helper()
            first, second = lambda: 1, lambda: 2
            assert first() == 1 and second() == 2
            assert list(values()) == [1, 1]
            asyncio.run(task())
        ''')
        trace, _ = self.run_target('--script', 'app.py')
        lambdas = [n for n in trace['nodes'] if n['kind'] == 'LAMBDA']
        self.assertEqual(len(lambdas), 2)
        self.assertEqual(len({n['id'] for n in lambdas}), 2)
        values = next(n for n in trace['nodes'] if n['name'] == 'values')
        self.assertTrue(values['resumable'])
        self.assertEqual(values['profile_calls'], 3)
        self.assertTrue(any(n['name'] == 'task' and n['resumable'] for n in trace['nodes']))

    def test_bridge_finds_runtime_additions_and_preserves_static_graph(self):
        self.write('app.py', '''
            class Service:
                def run(self): return 1
            def helper(): pass
            def main():
                helper()
                name = ''.join(['r', 'un'])
                getattr(Service(), name)()
            main()
        ''')
        _, graph = self.static_analysis()
        original = (self.static / 'graph_result.json').read_bytes()
        self.run_target('--script', 'app.py')
        out = self.base / 'hybrid.json'
        result = subprocess.run([sys.executable, str(CLI), 'compare', '--static-dir', str(self.static),
                                 '--trace', str(self.trace), '--out', str(out)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        hybrid = json.loads(out.read_text(encoding='utf-8'))
        self.assertEqual(hybrid['static_graph'], graph)
        self.assertEqual((self.static / 'graph_result.json').read_bytes(), original)
        self.assertTrue(any(e['source'] == 'FUNCTION:app.main' and e['target'] == 'METHOD:app.Service.run'
                            and e['status'] == 'additional' for e in hybrid['runtime_edges']))
        self.assertTrue(any(e['target'] == 'FUNCTION:app.helper' and e['status'] == 'confirmed'
                            for e in hybrid['runtime_edges']))
        self.assertTrue(any(e['target'] == 'CLASS:app.Service' and e['status'] == 'scope_entry'
                            for e in hybrid['runtime_edges']))
        self.assertGreater(hybrid['summary']['observed_function_relations'], 0)

    def test_decorators_nested_functions_and_redefinitions_map_exact_lines(self):
        self.write('app.py', '''
            def decorate(fn): return fn
            @decorate
            def wrapped(): pass
            def outer():
                def inner(): wrapped()
                inner()
            def duplicate(): pass
            old = duplicate
            def duplicate(): pass
            outer()
            old()
            duplicate()
        ''')
        symbols, _ = self.static_analysis()
        self.run_target('--script', 'app.py')
        hybrid = compare(self.static, self.trace)
        mapped = {m['static_id'] for m in hybrid['node_mapping'].values()}
        for symbol in symbols['symbols']:
            if symbol['kind'] in ('FUNCTION', 'METHOD'):
                self.assertIn(symbol['id'], mapped)

    def test_source_mismatch_blocks_unsafe_mapping(self):
        self.write('app.py', 'def work(): pass\nwork()\n')
        self.static_analysis()
        self.write('app.py', 'def work(): return 1\nwork()\n')
        self.run_target('--script', 'app.py')
        hybrid = compare(self.static, self.trace)
        self.assertEqual(hybrid['file_verification']['app.py'], 'source_mismatch')
        self.assertTrue(all(m['static_id'] is None for m in hybrid['node_mapping'].values()))
        self.assertIsNone(hybrid['summary']['observed_relation_recall'])

    def test_missing_snapshots_keep_observations_unmapped(self):
        self.write('app.py', 'def work(): pass\nwork()\n')
        symbols, _ = self.static_analysis()
        del symbols['analysis_sources']
        save_json(symbols, self.static / 'symbol_result.json')
        self.run_target('--script', 'app.py')
        hybrid = compare(self.static, self.trace)
        self.assertEqual(hybrid['file_verification']['app.py'], 'static_source_missing')
        self.assertGreater(hybrid['summary']['unmapped_runtime_edges'], 0)

    def test_supplemental_candidates_do_not_inflate_selected_graph_recall(self):
        self.write('app.py', 'def work(): pass\nwork()\n')
        _, graph = self.static_analysis()
        calls = [e for e in graph['edges'] if e['type'] == 'CALLS']
        graph['edges'] = [e for e in graph['edges'] if e['type'] != 'CALLS']
        graph['supplemental_edges'] = calls
        save_json(graph, self.static / 'graph_result.json')
        self.run_target('--script', 'app.py')
        hybrid = compare(self.static, self.trace)
        self.assertEqual(hybrid['summary']['confirmed_relations'], 0)
        self.assertGreater(hybrid['summary']['additional_relations'], 0)

    def test_excluded_environment_directory_is_outside_collected_scope(self):
        self.write('.venv/dependency.py', 'def work(): pass\n')
        self.write('app.py', 'import sys\nsys.path.insert(0, ".venv")\nimport dependency\ndependency.work()\n')
        trace, _ = self.run_target('--script', 'app.py')
        self.assertFalse(any(n['file'].startswith('.venv/') for n in trace['nodes']))

    def test_main_entry_point_accepts_saved_trace(self):
        self.write('app.py', 'def work(): pass\nwork()\n')
        self.run_target('--script', 'app.py')
        with contextlib.redirect_stdout(io.StringIO()):
            analyzer.run(self.root, self.static, dynamic_trace=self.trace)
        self.assertTrue((self.static / 'hybrid_graph.json').is_file())

    def test_no_fresh_trace_does_not_reuse_previous_output(self):
        self.trace.write_text('{"old": true}', encoding='utf-8')
        self.write('app.py', 'import os\nos._exit(3)\n')
        result = subprocess.run([sys.executable, str(CLI), 'record', str(self.root),
                                 '--script', 'app.py', '--out', str(self.trace)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 1)
        self.assertIn('without writing a trace', result.stderr)
        self.assertEqual(json.loads(self.trace.read_text(encoding='utf-8')), {'old': True})

    def test_output_cannot_overwrite_comparison_inputs(self):
        self.write('app.py', 'def work(): pass\nwork()\n')
        self.static_analysis()
        self.run_target('--script', 'app.py')
        with self.assertRaises(ValueError):
            compare(self.static, self.trace, self.trace)


if __name__ == '__main__':
    unittest.main()

"""Reproducible offline checks for ../test_code/Sublist3r on Windows.

Run through dynamic_analysis.py with --module unittest and discover this file,
or run it directly with the target dependencies installed. Results are written
under KnitCode's ignored out/sublist3r directory.
"""
import contextlib
import io
import json
from pathlib import Path
import socket
import sys
import threading
import unittest
from unittest.mock import Mock, patch

TOOL_ROOT = Path(__file__).resolve().parents[1]
TARGET_ROOT = TOOL_ROOT.parent / 'test_code' / 'Sublist3r'
OUTPUT = TOOL_ROOT / 'out' / 'sublist3r'
sys.path.insert(0, str(TARGET_ROOT))

import dns.resolver
import requests
import sublist3r as target


class LocalSublist3rChecks(unittest.TestCase):
    def setUp(self):
        OUTPUT.mkdir(parents=True, exist_ok=True)
        self.resources = contextlib.ExitStack()
        self.addCleanup(self.resources.close)
        for owner, method in ((socket.socket, 'connect'), (socket.socket, 'connect_ex'),
                              (socket, 'getaddrinfo'), (dns.resolver.Resolver, 'resolve')):
            self.resources.enter_context(patch.object(
                owner, method, side_effect=AssertionError('Unexpected network operation')))

    @staticmethod
    def fixed_response(method, url, **kwargs):
        if url.startswith('https://api.sublist3r.com/'):
            payload = ['api.example.test', 'www.example.test', 'api.example.test', 'example.test']
        elif url.startswith('https://www.threatcrowd.org/'):
            payload = {'subdomains': ['mail.example.test', 'api.example.test',
                                      'outside.other.test', 'example.test']}
        else:
            raise AssertionError(f'Unexpected HTTP fixture URL: {url}')
        response = requests.Response()
        response.status_code = 200
        response.encoding = 'utf-8'
        response._content = json.dumps(payload).encode('utf-8')
        return response

    def test_cli_arguments(self):
        with patch.object(sys, 'argv', ['sublist3r.py', '-d', 'example.test', '-n',
                                       '-e', 'passivedns,threatcrowd', '-t', '2']):
            args = target.parse_args()
        self.assertEqual(args.domain, 'example.test')
        self.assertEqual(args.engines, 'passivedns,threatcrowd')
        self.assertEqual(args.threads, 2)
        self.assertTrue(args.no_color)

    def test_invalid_domain(self):
        result = target.main('invalid', 2, None, None, True, False, False, 'passivedns')
        self.assertEqual(result, [])

    def test_sorting(self):
        domains = ['b.example.test', 'www.a.example.test', 'example.test',
                   'a.example.test', 'www.example.test']
        self.assertEqual(sorted(domains, key=target.subdomain_sorting_key),
                         ['example.test', 'www.example.test', 'a.example.test',
                          'www.a.example.test', 'b.example.test'])

    def test_passive_dns_extracts_and_deduplicates(self):
        with patch.object(requests.Session, 'request', side_effect=self.fixed_response):
            engine = target.PassiveDNS('http://example.test', q=[], silent=True, verbose=False)
            self.assertEqual(engine.enumerate(), ['api.example.test', 'www.example.test'])

    def test_threatcrowd_filters_domains(self):
        with patch.object(requests.Session, 'request', side_effect=self.fixed_response):
            engine = target.ThreatCrowd('http://example.test', q=[], silent=True, verbose=False)
            self.assertEqual(engine.enumerate(), ['mail.example.test', 'api.example.test'])

    @unittest.skipUnless(sys.platform.startswith('win'), 'Sublist3r uses thread workers on Windows')
    def test_main_runs_real_workers_and_saves_file(self):
        self.assertTrue(issubclass(target.enumratorBaseThreaded, threading.Thread))
        saved = OUTPUT / 'subdomains.txt'
        with patch.object(requests.Session, 'request', side_effect=self.fixed_response) as request:
            with contextlib.redirect_stdout(io.StringIO()):
                result = target.main('example.test', 2, str(saved), None, True, False,
                                     False, 'passivedns,threatcrowd')
        expected = ['www.example.test', 'api.example.test', 'mail.example.test']
        self.assertEqual(result, expected)
        # Windows text translation adds blank lines to the original writer's
        # os.linesep output. Compare domain content and retain the raw artifact.
        written_domains = [line for line in saved.read_text(encoding='utf-8').splitlines() if line]
        self.assertEqual(written_domains, expected)
        self.assertEqual(request.call_count, 2)

    def test_request_failure_is_handled(self):
        with patch.object(requests.Session, 'request', side_effect=requests.RequestException('fixture error')):
            engine = target.PassiveDNS('http://example.test', q=[], silent=True, verbose=False)
            self.assertEqual(engine.enumerate(), [])

    def test_portscan_runs_threads_with_fixed_socket_results(self):
        connection = Mock()
        connection.connect_ex.side_effect = lambda address: 0 if address[1] == 80 else 1
        scanner = target.portscan(['api.example.test', 'mail.example.test'], ['80', '443'])
        console = io.StringIO()
        with patch.object(socket, 'socket', return_value=connection) as factory:
            with contextlib.redirect_stdout(console):
                scanner.run()
                for thread in threading.enumerate():
                    callback = getattr(thread, '_target', None)
                    if getattr(callback, '__self__', None) is scanner:
                        thread.join(timeout=5)
                        self.assertFalse(thread.is_alive())
        self.assertEqual(factory.call_count, 4)
        self.assertEqual(connection.connect_ex.call_count, 4)
        self.assertEqual(console.getvalue().count('Found open ports:'), 2)
        self.assertNotIn('443', console.getvalue())

    def test_subbrute_extract_hosts(self):
        result = target.subbrute.extract_hosts(
            ' api.example.test. www.example.test outside.other.test ', 'example.test')
        self.assertEqual(result, ['api.example.test', 'www.example.test'])

    def test_subbrute_extract_subdomains_from_local_file(self):
        source = OUTPUT / 'hosts-input.txt'
        source.write_text('alpha.example.test beta.example.test alpha.example.test', encoding='utf-8')
        self.assertEqual(target.subbrute.extract_subdomains(str(source)), ['alpha', 'beta'])


if __name__ == '__main__':
    unittest.main(verbosity=2)

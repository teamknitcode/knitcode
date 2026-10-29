"""Run both Git entrypoints from the installed layout, outside this checkout."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

from scripts.package_extension import package


class GitValidationPackageTests(unittest.TestCase):
    def test_history_and_integrated_report_from_vsix(self):
        with tempfile.TemporaryDirectory(prefix='knit package ') as tmp:
            base = Path(tmp)
            repo = base / 'target project'
            repo.mkdir()
            def git(*args):
                subprocess.run(['git', '-C', str(repo), *args], check=True,
                               capture_output=True)
            git('init')
            git('config', 'user.email', 'test@example.com')
            git('config', 'user.name', 'Package Test')
            source = repo / 'app.py'
            source.write_text("raise RuntimeError('target must not run')\ndef target(): return 1\ndef caller(): return target()\n")
            git('add', '.')
            git('commit', '-m', 'feat: initial functions')
            source.write_text(source.read_text().replace('return 1', 'return 2'))
            git('add', '.')
            git('commit', '-m', 'fix: target value')
            archive = package(base / 'test.vsix')
            with ZipFile(archive) as z:
                self.assertIsNone(z.testzip())
                z.extractall(base / 'installed')
            vendor = base / 'installed/extension/vendor'
            def run(script, *args):
                result = subprocess.run([sys.executable, '-I', '-B',
                    str(vendor / 'git_validation' / script), str(repo), *args],
                    cwd=base, capture_output=True, text=True, timeout=60)
                if result.returncode:
                    self.fail(result.stdout + result.stderr)
                return result
            summary = json.loads(run('vscode_json_cli.py', '--commits', '10').stdout)
            self.assertTrue(summary['available'])
            self.assertEqual(summary['analyzed_commits'], 2)
            self.assertEqual(summary['files']['app.py']['functions'][0]['name'], 'target')
            source.write_text(source.read_text().replace('return 2', 'return 3'))
            current = subprocess.run([sys.executable, '-I', '-B', str(vendor / 'vscode_export.py'), str(repo)],
                                     cwd=base, check=True, capture_output=True, text=True, timeout=60)
            changed = json.loads(current.stdout)['working_changes']
            self.assertTrue(changed['available'])
            self.assertEqual(changed['files'][0]['functions'][0]['kind'], 'modified')
            report = base / 'report'
            run('integrated_cli.py', '--commits', '10', '--output', str(report))
            self.assertTrue((report / 'index.html').is_file())
            self.assertTrue((report / 'git/git_insights.json').is_file())
            self.assertIn('target', (report / 'index.html').read_text())

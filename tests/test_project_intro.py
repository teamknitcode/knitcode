from pathlib import Path
import tempfile
import unittest

from project_intro import project_intro


class ProjectIntroTests(unittest.TestCase):
    def test_readme_description_skips_badges_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'README.md').write_text(
                '# Example\n\n[![build](badge.svg)](https://example.com)\n\n'
                '**Example** sends [HTTP requests](https://example.com).\n\n'
                '```python\nraise RuntimeError("do not execute")\n```\n')
            intro = project_intro(root)
            self.assertEqual(intro['name'], 'Example')
            self.assertEqual(intro['description'], 'Example sends HTTP requests.')
            self.assertEqual(intro['line'], 5)
            self.assertEqual(intro['source'], 'README.md')

    def test_missing_readme_and_external_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / 'project'
            root.mkdir()
            self.assertIsNone(project_intro(root)['description'])
            (base / 'private.md').write_text('Outside project')
            (root / 'README.md').symlink_to(base / 'private.md')
            self.assertIsNone(project_intro(root)['description'])

    def test_rst_title_is_not_mistaken_for_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'README.rst').write_text('Example\n=======\n\nA reporting tool.\n')
            intro = project_intro(root)
            self.assertEqual(intro['name'], 'Example')
            self.assertEqual(intro['description'], 'A reporting tool.')

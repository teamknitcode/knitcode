import subprocess
import tempfile
from pathlib import Path
import unittest
from vscode_export import export_project


class WorkingChangeTests(unittest.TestCase):
    def test_saved_staged_added_deleted_and_invalid_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def git(*args):
                subprocess.run(['git','-C',tmp,*args],check=True,capture_output=True)
            git('init'); git('config','user.name','Test'); git('config','user.email','test@example.com')
            (root/'app.py').write_text('def target(): return 1\ndef caller(): return target()\n')
            (root/'gone.py').write_text('def removed(): pass\n')
            git('add','.'); git('commit','-m','initial')
            (root/'app.py').write_text('def target(): return 2\ndef caller(): return target()\n')
            git('add','app.py')
            (root/'gone.py').unlink()
            (root/'new.py').write_text('def fresh(): pass\n')
            (root/'broken.py').write_text('def bad(:')
            data=export_project(root)
            changes=data['working_changes']
            self.assertTrue(changes['available'])
            rows={r['file']:r for r in changes['files']}
            target=rows['app.py']['functions'][0]
            self.assertEqual(target['kind'],'modified')
            self.assertTrue(target['node_id'])
            callers={n['id']:n['name'] for n in data['nodes']}
            self.assertTrue(any(callers[c].endswith('.caller') for c in target['callers']))
            self.assertEqual(rows['gone.py']['functions'][0]['kind'],'deleted')
            self.assertIsNone(rows['gone.py']['functions'][0]['node_id'])
            self.assertEqual(rows['new.py']['functions'][0]['kind'],'added')
            self.assertTrue(rows['broken.py']['error'])

    def test_whitespace_does_not_mark_function_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for args in [('init',),('config','user.name','Test'),('config','user.email','test@example.com')]:
                subprocess.run(['git','-C',tmp,*args],check=True,capture_output=True)
            source=root/'app.py';source.write_text('def target(): return 1\n')
            for args in [('add','.'),('commit','-m','initial')]:
                subprocess.run(['git','-C',tmp,*args],check=True,capture_output=True)
            source.write_text('# comment\ndef target(): return 1\n')
            self.assertEqual(export_project(root)['working_changes']['files'][0]['functions'],[])

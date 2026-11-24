"""Exercise device routing without requiring a GPU in the team's test environment."""
import contextlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from unittest import TestCase, mock

FILE = Path(__file__).resolve().parents[1] / 'vscode-extension/natural_language/local_model.py'
spec = importlib.util.spec_from_file_location('knitcode_test_model', FILE)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class DeviceTests(TestCase):
    def check_dispatch(self, available, requested, expected):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dest = root / 'models/base'
            dest.mkdir(parents=True)
            (dest / 'ready.json').write_text(json.dumps(worker.MODELS['base']))
            tokenizer, model = mock.Mock(), mock.Mock()
            tokenizer.side_effect = lambda code, **opts: batch if opts.get('return_tensors') else {'input_ids': [1, 2]}
            batch = mock.Mock()
            batch.to.return_value = {'input_ids': mock.Mock(shape=(1, 2))}
            tokenizer.decode.return_value = 'Return a value.'
            model.generate.return_value = [mock.Mock(tolist=lambda: [1, 2])]
            torch = mock.Mock()
            torch.cuda.is_available.return_value = available
            torch.inference_mode = contextlib.nullcontext
            request = {'sources': [{'id': 'S1', 'text': 'def f(): return 1'}]}
            with mock.patch.dict(sys.modules, torch=torch), mock.patch.dict(worker.os.environ), mock.patch.object(
                    worker, 'load_model', return_value=(tokenizer, model)) as load:
                session = []
                first = worker.infer(root, 'base', request, requested, session)
                second = worker.infer(root, 'base', request, requested, session)
            self.assertEqual(first['device'], expected)
            self.assertFalse(first['reused'])
            self.assertTrue(second['reused'])
            load.assert_called_once_with(dest, 'base', expected)
            self.assertEqual(batch.to.call_args_list, [mock.call(expected), mock.call(expected)])

    def test_cuda_inputs_and_model_share_device(self):
        self.check_dispatch(True, 'cuda', 'cuda')

    def test_driver_unavailable(self):
        self.check_dispatch(False, 'cuda', 'cpu')

    def test_cpu_preference(self):
        self.check_dispatch(True, 'cpu', 'cpu')

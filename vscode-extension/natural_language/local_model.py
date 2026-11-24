"""Optional CPU-only CodeT5 worker. JSON stdin/stdout; never imports target code.

--setup creates a dedicated environment and downloads pinned public weights.
Normal inference is offline, uses no remote custom code, and exits after one request.
"""
import argparse
import ast
import contextlib
import json
import io
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import time
import tokenize

MODELS = {
    'small': {
        'repo': 'stmnk/codet5-small-code-summarization-python',
        'revision': 'e1c6b75d605e91929da00d024393819ff035c98c',
        'tokenizer': 'stmnk/codet5-small-code-summarization-python',
        'tokenizer_revision': 'e1c6b75d605e91929da00d024393819ff035c98c',
        'weights': 'model.safetensors',
    },
    'base': {
        'repo': 'Salesforce/codet5-base-codexglue-sum-python',
        'revision': 'a24de036787ca6acb85b82fb14c2bc6d70118b72',
        'tokenizer': 'Salesforce/codet5-base',
        'tokenizer_revision': '02cd2d31bb7c6d0e4d91156167b2de044989c733',
        'weights': 'pytorch_model.bin',
    },
}


def cpu_environment(offline=True):
    os.environ.update(CUDA_VISIBLE_DEVICES='', HIP_VISIBLE_DEVICES='',
                      HF_HUB_DISABLE_TELEMETRY='1', HF_HUB_DISABLE_XET='1',
                      TOKENIZERS_PARALLELISM='false', PYTHONUTF8='1',
                      OMP_NUM_THREADS='2', MKL_NUM_THREADS='2')
    if offline:
        os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    else:
        os.environ.pop('HF_HUB_OFFLINE', None)
        os.environ.pop('TRANSFORMERS_OFFLINE', None)


def runtime_python(runtime):
    return runtime / 'venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def setup(runtime, model):
    if not (3, 11) <= sys.version_info[:2] <= (3, 13):
        raise ValueError('Use Python 3.11, 3.12 or 3.13 for local model setup.')
    import venv
    cpu_environment(False)
    runtime.mkdir(parents=True, exist_ok=True)
    print('Creating dedicated CPU environment...', flush=True)
    py = runtime_python(runtime)
    if not py.exists():
        venv.EnvBuilder(with_pip=True).create(runtime / 'venv')
    commands = [
        [str(py), '-m', 'pip', 'install', '--disable-pip-version-check',
         'torch==2.8.0', '--index-url', 'https://download.pytorch.org/whl/cpu'],
        [str(py), '-m', 'pip', 'install', '--disable-pip-version-check',
         'transformers==4.57.6', 'huggingface-hub==0.36.2', 'safetensors==0.7.0',
         'ctranslate2==4.6.2', 'sentencepiece==0.2.1'],
        [str(py), '-I', '-B', str(Path(__file__).resolve()), '--download',
         '--runtime', str(runtime), '--model', model],
        [str(py), '-I', '-B', str(Path(__file__).with_name('translate_ko.py')),
         '--install', '--runtime', str(runtime)],
    ]
    for command in commands:
        subprocess.run(command, check=True)
    print('Local CodeT5 CPU setup complete.', flush=True)


def download(runtime, model):
    cpu_environment(False)
    from huggingface_hub import snapshot_download
    config = MODELS[model]
    destination = runtime / 'models' / model
    marker = destination / 'ready.json'
    try:
        verified = json.loads(marker.read_text(encoding='utf-8')) == config
    except (OSError, ValueError):
        verified = False
    if verified and all((destination / f).is_file() for f in
                        ('config.json', 'vocab.json', 'merges.txt', config['weights'])):
        load_model(destination, model)
        print('Reusing existing CodeT5 model.', flush=True)
        return
    # Invalidate an old success marker before retrying installation.
    (destination / 'ready.json').unlink(missing_ok=True)
    snapshot_download(config['repo'], revision=config['revision'], local_dir=destination,
                      allow_patterns=['config.json', config['weights']])
    snapshot_download(config['tokenizer'], revision=config['tokenizer_revision'],
                      local_dir=destination, allow_patterns=[
                          'vocab.json', 'merges.txt', 'tokenizer.json',
                          'tokenizer_config.json', 'special_tokens_map.json', 'added_tokens.json'])
    # Verify local loading before marking the installation ready; no target code involved.
    cpu_environment()
    tokenizer, loaded = load_model(destination, model)
    del tokenizer, loaded
    (destination / 'ready.json').write_text(json.dumps(config), encoding='utf-8')


def load_model(destination, model):
    import torch
    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    tokenizer = AutoTokenizer.from_pretrained(str(destination), local_files_only=True,
                                              trust_remote_code=False)
    loaded = AutoModelForSeq2SeqLM.from_pretrained(
        str(destination), local_files_only=True, trust_remote_code=False,
        use_safetensors=(model == 'small'), dtype=torch.float32)
    loaded.to('cpu').eval()
    return tokenizer, loaded


class RemoveDocstrings(ast.NodeTransformer):
    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str):
            node.body.pop(0)
        if not node.body:
            node.body = [ast.Pass()]
        return node
    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef


def prepare_code(text):
    if not isinstance(text, str) or not text.strip() or len(text) > 60000:
        raise ValueError('Invalid or oversized function source.')
    tree = ast.parse(textwrap.dedent(text))
    if len(tree.body) != 1 or not isinstance(tree.body[0], (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise ValueError('A complete Python function is required.')
    return ast.unparse(ast.fix_missing_locations(RemoveDocstrings().visit(tree)))


def model_input(code):
    # CodeT5's CodeXGLUE loader joins lexical code tokens with spaces.
    ignored = {tokenize.ENCODING, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
               tokenize.DEDENT, tokenize.ENDMARKER, tokenize.COMMENT}
    tokens = tokenize.generate_tokens(io.StringIO(code).readline)
    spaced = ' '.join(token.string for token in tokens if token.type not in ignored)
    return ' '.join(spaced.split()).replace('</s>', '<unk>')


def infer(runtime, model, request):
    cpu_environment()
    sources = request.get('sources')
    if not isinstance(sources, list) or not 1 <= len(sources) <= 3:
        raise ValueError('Select one to three functions.')
    prepared = []
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get('id'), str):
            raise ValueError('Invalid source identifier.')
        prepared.append((source['id'], model_input(prepare_code(source.get('text')))))
    destination = runtime / 'models' / model
    marker = destination / 'ready.json'
    if not marker.exists() or json.loads(marker.read_text(encoding='utf-8')) != MODELS[model]:
        raise ValueError('MODEL_NOT_READY: Run local CPU model setup first.')
    import torch
    start = time.monotonic()
    tokenizer, loaded = load_model(destination, model)
    results = []
    for sid, code in prepared:
        all_ids = tokenizer(code, truncation=False)['input_ids']
        inputs = tokenizer(code, return_tensors='pt', truncation=True, max_length=512)
        with torch.inference_mode():
            generated = loaded.generate(**inputs, max_new_tokens=64, do_sample=False,
                                        num_beams=1)
        english = tokenizer.decode(generated[0], skip_special_tokens=True).strip()
        output_ids = generated[0].tolist()
        results.append({'id': sid, 'english': english,
                        'input_tokens': len(all_ids), 'used_tokens': int(inputs['input_ids'].shape[-1]),
                        'truncated': len(all_ids) > 512,
                        'output_truncated': len(output_ids) >= 65 and output_ids[-1] != tokenizer.eos_token_id})
    return {'model': MODELS[model]['repo'], 'revision': MODELS[model]['revision'],
            'device': 'cpu', 'threads': 2, 'seconds': round(time.monotonic() - start, 2),
            'summaries': results}


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stdin.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--model', choices=MODELS, default='base')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--setup', action='store_true')
    modes.add_argument('--download', action='store_true')
    args = parser.parse_args()
    try:
        if args.setup:
            setup(args.runtime.resolve(), args.model)
        elif args.download:
            download(args.runtime.resolve(), args.model)
        else:
            raw = sys.stdin.read(200001)
            if len(raw) > 200000:
                raise ValueError('Input exceeds limit.')
            with contextlib.redirect_stdout(sys.stderr):
                result = infer(args.runtime.resolve(), args.model, json.loads(raw))
            print(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        if args.setup or args.download:
            print(f'Setup failed: {error}', file=sys.stderr)
        else:
            print(json.dumps({'error': str(error)[:1200]}, ensure_ascii=False))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

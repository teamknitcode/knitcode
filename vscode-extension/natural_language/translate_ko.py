"""Install the Argos English–Korean 1.1 model and translate short summaries offline."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import os
import subprocess
import shutil
import sys
import tempfile
from urllib.error import URLError
from urllib.request import Request, urlopen
from zipfile import ZipFile

MODEL = 'argos-en-ko-1.1'
URL = 'https://argos-net.com/v1/translate-en_ko-1_1.argosmodel'
SHA256 = 'e03d8e65e6d44525ec5808c3409fcf8728c76c2c76925372b6d3dc3278de17fc'
FILES = ('sentencepiece.model', 'model/model.bin', 'model/shared_vocabulary.txt', 'metadata.json', 'README.md')
IDENTIFIER = re.compile(r"`[^`\n]+`|\b[A-Za-z_]\w*(?:\.\w+)+\b|\b\w+_\w+\b|\b[a-z]+[A-Z]\w*\b|\b[A-Za-z_]\w*\(\)")


def translate(directory, sentences):
    os.environ.setdefault("UCX_VFS_ENABLE", "n")
    import ctranslate2
    import sentencepiece
    # Python opens Unicode paths; native loaders receive only bytes and ASCII keys.
    sp = sentencepiece.SentencePieceProcessor(
        model_proto=(directory / 'sentencepiece.model').read_bytes())
    model_dir = directory / 'model'
    engine = ctranslate2.Translator(
        MODEL, device='cpu', compute_type='int8', inter_threads=1, intra_threads=2,
        files={name: (model_dir / name).read_bytes()
               for name in ('model.bin', 'shared_vocabulary.txt')})
    texts = [re.sub(r'\s+([.,!?;:])', r'\1', s).strip() for s in sentences]
    batches = [sp.encode(s, out_type=str) for s in texts]
    results = engine.translate_batch(batches, beam_size=4, max_decoding_length=160)
    translated = []
    for text, result in zip(texts, results):
        line = sp.decode(result.hypotheses[0]).strip()
        intact = all(token in line for token in IDENTIFIER.findall(text))
        translated.append(line if intact and re.search('[가-힣]', line) else None)
    return translated


def install(runtime):
    destination = runtime / 'models' / MODEL
    destination.mkdir(parents=True, exist_ok=True)
    marker = destination / 'ready.json'
    if marker.is_file() and all((destination / f).is_file() for f in FILES):
        try:
            version = json.loads(marker.read_text(encoding='utf-8'))
            if version.get('archive_sha256') == SHA256 and translate(destination, ['Read the file.'])[0]:
                return
        except (OSError, ValueError, RuntimeError):
            pass  # Repair an incomplete previous installation from the verified archive.
    with tempfile.TemporaryDirectory(dir=destination.parent) as temp:
        stage = Path(temp)
        package = stage / 'download.zip'
        try:
            request = Request(URL, headers={'User-Agent': 'KnitCode/0.4.22'})
            with urlopen(request, timeout=90) as response, package.open('wb') as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
        except (URLError, TimeoutError):
            curl = shutil.which('curl.exe' if os.name == 'nt' else 'curl')
            if not curl:
                raise
            subprocess.run([curl, '--fail', '--location', '--silent', '--show-error',
                            '--max-time', '180', '--output', str(package), URL], check=True)
        with package.open('rb') as stream:
            checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        if checksum != SHA256:
            raise ValueError('Downloaded English–Korean package failed checksum verification.')
        with ZipFile(package) as archive:
            for name in FILES:
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open('en_ko/' + name) as src, target.open('wb') as out:
                    shutil.copyfileobj(src, out)
        if not translate(stage, ['Read the file.'])[0]:
            raise ValueError('English–Korean translation smoke test failed.')
        marker.unlink(missing_ok=True)
        for name in FILES:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            (stage / name).replace(target)
        ready = stage / 'ready.json'
        ready.write_text(json.dumps({'model': MODEL, 'archive_sha256': SHA256}), encoding='utf-8')
        ready.replace(marker)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    if args.install:
        install(args.runtime)
    else:
        sys.stdin.reconfigure(encoding='utf-8')
        texts = json.loads(sys.stdin.read(14000))
        if not isinstance(texts, list) or not 1 <= len(texts) <= 3 or not all(
                isinstance(t, str) and 0 < len(t) <= 3000 for t in texts):
            raise ValueError('Expected one to three English summaries.')
        print(json.dumps(translate(args.runtime / 'models' / MODEL, texts)))

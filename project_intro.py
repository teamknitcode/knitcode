"""Bounded, read-only project introduction from repository documentation."""
from pathlib import Path
import re


def project_intro(root):
    root = Path(root).resolve()
    title = root.name
    for name in ('README.md', 'README.rst', 'README.txt', 'README'):
        path = root / name
        if not path.is_file() or not path.resolve().is_relative_to(root):
            continue
        try:
            with path.open(encoding='utf-8', errors='replace') as stream:
                lines = stream.read(32000).splitlines()
        except OSError:
            continue
        paragraph = []
        fenced = False
        start = 1
        for number, raw in enumerate(lines, 1):
            line = raw.strip()
            if line.startswith(('```', '~~~')):
                fenced = not fenced
                continue
            if fenced:
                continue
            if number < len(lines) and re.fullmatch(r'[=\-]{3,}', lines[number].strip()):
                title = line[:160]
                continue
            if line.startswith('# '):
                title = line[2:].strip()[:160]
                continue
            if not line:
                if paragraph:
                    break
                continue
            if line.startswith(('#', '<', '!', '[!', '..', '|', '===', '---')):
                continue
            if not paragraph:
                start = number
            paragraph.append(line)
        if paragraph:
            text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', ' '.join(paragraph))
            text = re.sub(r'[*`]', '', text)[:500]
            return dict(name=title, description=text, source=name, line=start)
    return dict(name=title, description=None, source=None, line=None)

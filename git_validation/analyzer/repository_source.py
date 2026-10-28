"""Resolve local paths or public GitHub URLs into analyzable repositories."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse


GITHUB_PART = re.compile(r'^[A-Za-z0-9_.-]+$')


def github_clone_url(value: str) -> str | None:
    """Convert a GitHub repo or nested issue/PR URL to its canonical clone URL."""
    parsed = urlparse(value)
    if parsed.scheme not in {'http', 'https'} or parsed.hostname not in {'github.com', 'www.github.com'}:
        return None
    parts = [part for part in parsed.path.split('/') if part]
    if len(parts) < 2:
        raise ValueError('GitHub URL must include owner and repository')
    owner, repository = parts[:2]
    if repository.endswith('.git'):
        repository = repository[:-4]
    if not owner or not repository or not GITHUB_PART.fullmatch(owner) or not GITHUB_PART.fullmatch(repository):
        raise ValueError('Invalid GitHub owner or repository name')
    return f'https://github.com/{owner}/{repository}.git'


def local_repository(value: str) -> Path:
    return Path(value).expanduser().resolve()


def github_identity(clone_url: str) -> tuple[str, str]:
    parts = [part for part in urlparse(clone_url).path.split('/') if part]
    owner, repository = parts[:2]
    return owner, repository[:-4] if repository.endswith('.git') else repository

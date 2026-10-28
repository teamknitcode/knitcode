"""Analyze committed source and Git history at one immutable revision."""
import argparse
from datetime import date
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile

from analyzer.extensions import enrich
from analyzer.git_insights import analyze, git
from analyzer.github_api import enrich_github
from analyzer.integration import join_results, write_integrated_report
from analyzer.repository_source import github_clone_url, github_identity
from git_insights_cli import write_report


def materialize(repo, head, snapshot):
    """Read blobs directly: no checkout filters, hooks, symlinks or target execution."""
    skipped = []
    for entry in git(repo, 'ls-tree', '-rz', head, raw=True).split(b'\0'):
        if not entry:
            continue
        metadata, raw_path = entry.split(b'\t', 1)
        mode, kind, sha = metadata.decode('ascii').split()
        path = raw_path.decode('utf-8')
        parts = PurePosixPath(path)
        if parts.is_absolute() or '..' in parts.parts or '\\' in path or ':' in path:
            raise ValueError('안전하게 스냅샷을 만들 수 없는 경로: ' + path)
        if kind != 'blob' or mode not in ('100644', '100755'):
            skipped.append(path)
            continue
        dest = snapshot.joinpath(*parts.parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(git(repo, 'cat-file', 'blob', sha, raw=True))
    return skipped


def run(repository, output='integrated_output', *, revision='HEAD', commits=100,
        pair_limit=40, since=None, until=None, aliases=None, source_roots=None,
        github_api=False, api_commits=20, static_timeout=600):
    if min(commits, pair_limit, api_commits, static_timeout) < 1:
        raise ValueError('분석 제한값은 1 이상이어야 합니다.')
    for value in (since, until):
        if value:
            date.fromisoformat(value)
    if since and until and since > until:
        raise ValueError('--since는 --until보다 늦을 수 없습니다.')
    aliases = aliases or {}
    if not isinstance(aliases, dict) or any(not isinstance(k, str) or not isinstance(v, str) or not v.strip() for k, v in aliases.items()):
        raise ValueError('aliases는 이메일 → 대표 식별자 문자열의 JSON 객체여야 합니다.')
    clone_url = github_clone_url(repository)
    if not clone_url and '://' in repository:
        raise ValueError('로컬 Git 경로 또는 GitHub 저장소 URL을 입력하세요.')
    out = Path(output).expanduser().resolve()
    if out.exists() and any(out.iterdir()):
        raise ValueError('기존 보고서를 보존하려면 비어 있는 새 출력 폴더를 지정하세요.')
    with tempfile.TemporaryDirectory(prefix='knit_integrated_', ignore_cleanup_errors=True) as temp:
        temp = Path(temp)
        repo = Path(repository).expanduser().resolve()
        if clone_url:
            repo = temp / 'repository'
            subprocess.run(['git', 'clone', '--quiet', '--no-checkout', '--', clone_url, str(repo)],
                           check=True, timeout=300, env=dict(os.environ, GIT_TERMINAL_PROMPT='0'))
        else:
            repo = Path(git(repo, 'rev-parse', '--show-toplevel').strip())
        try:
            head = git(repo, 'rev-parse', '--verify', '--end-of-options', revision + '^{commit}').strip()
        except ValueError:
            if not clone_url or revision.startswith('-'):
                raise
            head = git(repo, 'rev-parse', '--verify', '--end-of-options', 'refs/remotes/origin/' + revision + '^{commit}').strip()
        print('[1/3] 같은 커밋의 소스·변경 이력 분석:', head, flush=True)
        history = analyze(repo, revision=head, max_commits=commits, pair_limit=pair_limit,
                          since=since, until=until, aliases=aliases)
        enrich(repo, history)
        history['source'] = {'kind': 'github' if clone_url else 'local',
                             'input': clone_url.removesuffix('.git') if clone_url else str(repo),
                             'requested_revision': revision, 'snapshot': 'committed files only'}
        history['github'] = {'enabled': False, 'records': [], 'warnings': []}
        if clone_url:
            history['repository'] = '/'.join(github_identity(clone_url))
            history['github_url'] = clone_url.removesuffix('.git')
        if github_api:
            if clone_url:
                enrich_github(history, max_commits=api_commits)
            else:
                history['warnings'].append('GitHub API 연결은 GitHub URL 입력 시 사용할 수 있습니다.')
        snapshot_name = github_identity(clone_url)[1] if clone_url else repo.name
        snapshot = temp / 'snapshot' / snapshot_name
        snapshot.mkdir(parents=True)
        skipped = materialize(repo, head, snapshot)
        if skipped:
            history['warnings'].append('심볼릭 링크·서브모듈 제외: ' + ', '.join(skipped))
        staged = temp / 'report'
        print('[2/3] 팀 KnitCode 정적분석 실행', flush=True)
        command = [sys.executable, str(Path(__file__).parent.resolve() / 'static_bridge.py'),
                   str(snapshot), str(staged / 'static'), head]
        for root in source_roots or []:
            path = PurePosixPath(root)
            if path.is_absolute() or '..' in path.parts or '\\' in root or ':' in root:
                raise ValueError('--source-root는 저장소 내부 상대 경로여야 합니다.')
            command += ['--source-root', root]
        subprocess.run(command, check=True, timeout=static_timeout)
        ast_data = json.loads((staged / 'static/ast_result.json').read_text(encoding='utf-8'))
        for error in ast_data['parse_errors']:
            history['warnings'].append('정적분석 구문 해석 제외: ' + error['file'] + ' · ' + error['message'])
        symbols = json.loads((staged / 'static/symbol_result.json').read_text(encoding='utf-8'))
        graph = json.loads((staged / 'static/graph_result.json').read_text(encoding='utf-8'))
        data = join_results(history, symbols, graph)
        write_report(history, staged / 'git')
        write_integrated_report(data, staged)
        out.mkdir(parents=True, exist_ok=True)
        shutil.copytree(staged, out, dirs_exist_ok=True)
        print('[3/3] 완료:', out / 'index.html', flush=True)
        return data


def main():
    p = argparse.ArgumentParser(description='팀 정적분석 + GitHub 변경 이력 통합 분석')
    p.add_argument('repository', help='로컬 Git 경로 또는 GitHub URL')
    p.add_argument('--output', default='integrated_output')
    p.add_argument('--revision', default='HEAD')
    p.add_argument('--commits', type=int, default=100)
    p.add_argument('--pair-limit', type=int, default=40)
    p.add_argument('--since')
    p.add_argument('--until')
    p.add_argument('--aliases')
    p.add_argument('--source-root', action='append', dest='source_roots')
    p.add_argument('--github-api', action='store_true')
    p.add_argument('--api-commits', type=int, default=20)
    p.add_argument('--static-timeout', type=int, default=600)
    a = vars(p.parse_args())
    try:
        a['aliases'] = json.loads(Path(a['aliases']).read_text(encoding='utf-8-sig')) if a['aliases'] else None
        run(**a)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        p.exit(1, f'오류: {exc}\n')


if __name__ == '__main__':
    main()

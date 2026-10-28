"""Compare two committed revisions using the integrated KnitCode engine."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile

from analyzer.change_review import build_review, write_review
from analyzer.extensions import enrich
from analyzer.git_insights import analyze, git
from analyzer.github_api import enrich_github
from analyzer.repository_source import github_clone_url, github_identity
from git_insights_cli import write_report
from integrated_cli import materialize


def resolve_revision(repo, ref, remote=False):
    try:
        return git(repo, 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}').strip()
    except ValueError:
        if not remote or ref.startswith('-'):
            raise
        return git(repo, 'rev-parse', '--verify', '--end-of-options', 'refs/remotes/origin/' + ref + '^{commit}').strip()


def static_snapshot(repo, commit, side, temporary, output, name, source_roots, timeout):
    snapshot = temporary / side / name
    snapshot.mkdir(parents=True)
    skipped = materialize(repo, commit, snapshot)
    command = [sys.executable, str(Path(__file__).resolve().parent / 'static_bridge.py'),
               str(snapshot), str(output), commit]
    for root in source_roots or []:
        command += ['--source-root', root]
    subprocess.run(command, check=True, timeout=timeout)
    bundle = {}
    for key, filename in [('ast', 'ast_result.json'), ('symbols', 'symbol_result.json'), ('graph', 'graph_result.json')]:
        bundle[key] = json.loads((output / filename).read_text(encoding='utf-8'))
    return bundle, skipped


def run(repository, *, base='HEAD~1', head='HEAD', merge_base=False,
        output='reports/change_review', commits=200, pair_limit=40,
        max_depth=5, max_nodes=500, min_support=3, min_confidence=0.6,
        source_roots=None, static_timeout=600, source_limit=500_000,
        github_api=False, api_commits=20):
    if min(commits, pair_limit, max_depth, max_nodes, min_support, static_timeout,
           source_limit, api_commits) < 1:
        raise ValueError('커밋·표본·탐색·시간·크기 제한은 1 이상이어야 합니다.')
    if not 0 < min_confidence <= 1:
        raise ValueError('--min-confidence는 0 초과 1 이하여야 합니다.')
    for root in source_roots or []:
        path = PurePosixPath(root)
        if path.is_absolute() or '..' in path.parts or '\\' in root or ':' in root:
            raise ValueError('--source-root는 저장소 내부의 상대 경로여야 합니다.')
    out = Path(output).expanduser().resolve()
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError('출력 폴더가 비어 있지 않습니다. --output으로 새 폴더를 지정하세요.')
    clone_url = github_clone_url(repository)
    if not clone_url and '://' in repository:
        raise ValueError('로컬 Git 저장소 경로 또는 GitHub URL을 입력하세요.')
    with tempfile.TemporaryDirectory(prefix='knit_review_', ignore_cleanup_errors=True) as temporary:
        temporary = Path(temporary)
        if clone_url:
            repo = temporary / 'git_repository'
            print('[1/5] 대상 저장소 이력 가져오기', flush=True)
            subprocess.run(['git', 'clone', '--quiet', '--no-checkout', '--', clone_url, str(repo)],
                           check=True, timeout=300, env=dict(os.environ, GIT_TERMINAL_PROMPT='0'))
            name = github_identity(clone_url)[1]
        else:
            repo = Path(git(Path(repository).expanduser().resolve(), 'rev-parse', '--show-toplevel').strip())
            name = repo.name
        base_sha = resolve_revision(repo, base, bool(clone_url))
        head_sha = resolve_revision(repo, head, bool(clone_url))
        requested_base = base_sha
        if merge_base:
            common = git(repo, 'merge-base', '--all', base_sha, head_sha).splitlines()
            if len(common) != 1:
                raise ValueError('공통 조상이 하나로 확정되지 않습니다. --base에 비교할 커밋을 직접 지정하세요.')
            base_sha = common[0]
        staged = temporary / 'report'
        snapshots, warnings = {}, []
        if not merge_base:
            check = subprocess.run(['git', '-C', str(repo), 'merge-base', '--is-ancestor', base_sha, head_sha],
                                   capture_output=True, timeout=120)
            if check.returncode not in (0, 1):
                raise ValueError('커밋 조상 관계를 확인할 수 없습니다.')
            if check.returncode == 1:
                warnings.append('base는 head의 조상이 아닙니다. 두 끝점 비교이며 PR 변경 범위와 다를 수 있습니다. 필요하면 --merge-base를 사용하세요.')
        print('[2/5] 변경 전 정적분석: ' + base_sha, flush=True)
        snapshots['base'], skipped = static_snapshot(repo, base_sha, 'base', temporary,
            staged / 'base', name, source_roots, static_timeout)
        warnings.extend('base 링크/서브모듈 제외: ' + p for p in skipped)
        print('[3/5] 변경 후 정적분석: ' + head_sha, flush=True)
        snapshots['head'], skipped = static_snapshot(repo, head_sha, 'head', temporary,
            staged / 'head', name, source_roots, static_timeout)
        warnings.extend('head 링크/서브모듈 제외: ' + p for p in skipped)
        print('[4/5] 변경 영향·테스트·과거 동시 수정 분석', flush=True)
        # Never learn from the proposed change or any descendant of the base.
        # Keep recommendation learning strictly at base. Build the visible Git
        # report at head so the compared change and latest commit are included.
        history = analyze(repo, revision=base_sha, max_commits=commits,
                          pair_limit=pair_limit, source_limit=source_limit)
        git_report = analyze(repo, revision=head_sha, max_commits=commits,
                             pair_limit=pair_limit, source_limit=source_limit)
        enrich(repo, git_report)
        git_report['source'] = {'kind': 'github' if clone_url else 'local',
                                'input': clone_url.removesuffix('.git') if clone_url else str(repo),
                                'requested_revision': head, 'snapshot': 'committed files only'}
        git_report['github'] = {'enabled': False, 'records': [], 'warnings': []}
        if clone_url:
            git_report['repository'] = '/'.join(github_identity(clone_url))
            git_report['github_url'] = clone_url.removesuffix('.git')
        if github_api:
            if clone_url:
                enrich_github(git_report, max_commits=api_commits)
            else:
                git_report['warnings'].append(
                    'PR·Issue·CI API 연결은 GitHub URL 입력 시 사용할 수 있습니다.')
        data = build_review(repo, base_sha, head_sha, snapshots, history,
            max_depth=max_depth, max_nodes=max_nodes, min_support=min_support,
            min_confidence=min_confidence, source_limit=source_limit)
        data['repository'] = '/'.join(github_identity(clone_url)) if clone_url else name
        data['source'] = {'input': clone_url.removesuffix('.git') if clone_url else str(repo),
            'requested_base': base, 'requested_head': head, 'requested_base_sha': requested_base,
            'merge_base': merge_base, 'snapshot': 'committed files only'}
        data['warnings'].extend(warnings)
        data['git_summary'] = {
            'head': git_report['head'], 'analyzed_commits': len(git_report['commits']),
            'authors': len(git_report['authors']), 'pairs': len(git_report['pairs']),
            'hotspots': len(git_report.get('hotspots', [])),
            'github_api_enabled': git_report['github']['enabled'],
            'github_records': len(git_report['github'].get('records', [])),
            'github_warnings': git_report['github'].get('warnings', []),
            'note': ('git/report.html은 head에서 도달 가능한 변경 이력입니다. '
                     '동시 수정 추천 학습은 base까지의 별도 이력만 사용합니다.'),
        }
        if base_sha == head_sha:
            data['warnings'].append('base와 head가 같은 커밋입니다. 순변경이 없습니다.')
        # Compact evidence for every counted co-change commit; raw patches stay out of this report.
        data['history_evidence'] = [{'sha': c['sha'], 'date': c['date'], 'author': c['author'],
                                    'message': c['message'], 'pair_eligible': c['pair_eligible'],
                                    'files': [f['path'] for f in c['files']]}
                                   for c in history['commits']]
        write_report(git_report, staged / 'git')
        write_review(data, staged)
        out.mkdir(parents=True, exist_ok=True)
        shutil.copytree(staged, out, dirs_exist_ok=True)
        print('[5/5] 완료: ' + str(out / 'index.html'), flush=True)
        return data


def main():
    p = argparse.ArgumentParser(description='KnitCode: 변경 전후 구조·영향/테스트·동시 수정 누락 후보')
    p.add_argument('repository', help='분석할 GitHub URL 또는 로컬 Git 저장소')
    p.add_argument('--base', default='HEAD~1', help='비교 시작 리비전 (기본: HEAD 첫 부모)')
    p.add_argument('--head', default='HEAD', help='비교 종료 리비전')
    p.add_argument('--merge-base', action='store_true', help='base/head의 공통 조상부터 비교 (PR 방식)')
    p.add_argument('--output', default='reports/change_review')
    p.add_argument('--commits', type=int, default=200, help='base까지의 동시 수정 학습 커밋 상한')
    p.add_argument('--pair-limit', type=int, default=40)
    p.add_argument('--max-depth', type=int, default=5)
    p.add_argument('--max-nodes', type=int, default=500, help='변경 심볼 하나당 영향 노드 상한')
    p.add_argument('--min-support', type=int, default=3, help='동시 수정 최소 관측 횟수')
    p.add_argument('--min-confidence', type=float, default=0.6, help='방향별 동시 수정 비율 하한')
    p.add_argument('--source-root', action='append', dest='source_roots')
    p.add_argument('--static-timeout', type=int, default=600)
    p.add_argument('--source-limit', type=int, default=500_000)
    p.add_argument('--github-api', action='store_true',
                   help='GitHub URL의 PR·Issue·Checks·Status를 기존 Git 보고서에 연결')
    p.add_argument('--api-commits', type=int, default=20,
                   help='GitHub API로 조회할 최신 커밋 상한')
    args = vars(p.parse_args())
    try:
        run(**args)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        p.exit(1, f'오류: {exc}\n')


if __name__ == '__main__':
    main()

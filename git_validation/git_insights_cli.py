"""Run: python git_insights_cli.py PATH_OR_GITHUB_URL --output git_insights_output"""
import argparse
from datetime import date
import json
import os
from pathlib import Path
import subprocess
import tempfile

from analyzer.extensions import enrich
from analyzer.github_api import enrich_github
from analyzer.git_insights import analyze
from analyzer.repository_source import github_clone_url, github_identity


def write_report(data, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(data, ensure_ascii=False, indent=2)
    (output / 'git_insights.json').write_text(serialized, encoding='utf-8')
    template = (Path(__file__).parent / 'analyzer/templates/git_insights.html').read_text(encoding='utf-8')
    # JSON in a script element must not permit closing that element.
    embedded = serialized.replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    (output / 'report.html').write_text(template.replace('__REPORT_DATA__', embedded), encoding='utf-8')


def analyze_target(repository, *, revision='HEAD', github_api=False, api_commits=20, **options):
    """Analyze the requested target, never implicitly the Knitcode working tree."""
    clone_url = github_clone_url(repository)
    if not clone_url and '://' in repository:
        raise ValueError('GitHub 저장소 URL(https://github.com/OWNER/REPO)을 입력하세요.')
    with tempfile.TemporaryDirectory(prefix='knit_git_', ignore_cleanup_errors=True) as temporary:
        repo = Path(repository).expanduser().resolve()
        if clone_url:
            owner, name = github_identity(clone_url)
            repo = Path(temporary) / name
            print(f'[1/3] 분석 대상: {owner}/{name} — Git 이력 가져오기…', flush=True)
            env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
            subprocess.run(['git', 'clone', '--quiet', '--no-checkout', '--', clone_url, str(repo)],
                           check=True, timeout=300, env=env)
        else:
            print(f'[1/3] 분석 대상: {repo}', flush=True)
        print('[2/3] 대상 저장소의 커밋·작성자·함수 변경 분석…', flush=True)
        # Remote branch names are available without checking out target code.
        selected_revision = revision
        if clone_url and revision != 'HEAD' and not revision.startswith('-'):
            found = subprocess.run(['git', '-C', str(repo), 'rev-parse', '--verify',
                                    '--end-of-options', revision + '^{commit}'], capture_output=True)
            if found.returncode:
                selected_revision = 'refs/remotes/origin/' + revision
        data = analyze(repo, revision=selected_revision, **options)
        enrich(repo, data)
        data['github'] = {'enabled': False, 'records': [], 'warnings': []}
        data['source'] = {'kind': 'github' if clone_url else 'local',
                          'input': clone_url.removesuffix('.git') if clone_url else str(repo),
                          'requested_revision': revision}
        if clone_url:
            data['repository'] = '/'.join(github_identity(clone_url))
            data['github_url'] = clone_url.removesuffix('.git')
        if github_api:
            if clone_url:
                enrich_github(data, max_commits=api_commits)
            else:
                data['warnings'].append('API 연결은 GitHub URL 입력 시 사용할 수 있습니다.')
        return data


def main():
    p = argparse.ArgumentParser(description='Git 작성자·동시 변경·Python 함수 변경 분석 (외부 패키지 불필요)')
    p.add_argument('repository', nargs='?', help='분석할 외부 Python 프로젝트의 GitHub URL (또는 로컬 Git 경로)')
    p.add_argument('--repo-url', help='분석할 GitHub 프로젝트 URL; 위치 인자와 둘 중 하나만 지정')
    p.add_argument('--output', default='git_insights_output')
    p.add_argument('--revision', default='HEAD')
    p.add_argument('--commits', type=int, default=500)
    p.add_argument('--pair-limit', type=int, default=40)
    p.add_argument('--since', help='작성일 시작 YYYY-MM-DD (포함)')
    p.add_argument('--until', help='작성일 종료 YYYY-MM-DD (포함)')
    p.add_argument('--aliases', help='JSON: {"old@email": "canonical@email"}')
    p.add_argument('--github-api', action='store_true', help='Issue·PR·CI REST API 연결')
    p.add_argument('--api-commits', type=int, default=20, help='API로 조회할 최대 커밋 수')
    args = p.parse_args()
    try:
        if bool(args.repository) == bool(args.repo_url):
            raise ValueError('분석 대상 주소를 지정하세요: py git_insights_cli.py https://github.com/OWNER/REPO')
        if args.api_commits < 1:
            raise ValueError('--api-commits는 1 이상이어야 합니다.')
        target = args.repo_url or args.repository
        if args.repo_url and not github_clone_url(target):
            raise ValueError('--repo-url에는 GitHub 저장소 URL이 필요합니다.')
        for value in (args.since, args.until):
            if value:
                date.fromisoformat(value)
        if args.since and args.until and args.since > args.until:
            raise ValueError('--since는 --until보다 늦을 수 없습니다.')
        aliases = json.loads(Path(args.aliases).read_text(encoding='utf-8-sig')) if args.aliases else {}
        if not isinstance(aliases, dict) or any(not isinstance(k, str) or not isinstance(v, str) or not v.strip() for k, v in aliases.items()):
            raise ValueError('aliases는 이메일 → 대표 식별자 문자열의 JSON 객체여야 합니다.')
        data = analyze_target(target, revision=args.revision, github_api=args.github_api, api_commits=args.api_commits, max_commits=args.commits,
                              pair_limit=args.pair_limit, aliases=aliases, since=args.since, until=args.until)
        write_report(data, args.output)
        print(f'[3/3] 완료: {Path(args.output).resolve() / "report.html"}')
        print(f'분석 {len(data["commits"])} 커밋 / 작성자 {len(data["authors"])}명 / 파일 관계 {len(data["pairs"])}개')
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        p.exit(1, f'오류: {exc}\n')


if __name__ == '__main__':
    main()

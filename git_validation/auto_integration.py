"""Opt-in postprocessor for the unmodified KnitCode static engine.

This module is invoked by the small main.py adapter installed by the patch.
It neither imports nor executes analyzed project code.
"""
from __future__ import annotations

from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def add_report_link(static_report: Path, href: str = 'git_validation/index.html') -> None:
    if not static_report.is_file():
        return
    marker = '<!-- knitcode-git-validation-link -->'
    html = static_report.read_text(encoding='utf-8')
    if marker in html:
        return
    anchor = (marker + '\n'
        '<a href="' + href + '" target="_blank" rel="noopener" '
        'style="position:fixed;bottom:20px;right:20px;z-index:9999;'
        'border:1px solid #62739a;border-radius:12px;background:#18243c;'
        'color:white;padding:12px 16px;font:600 14px system-ui;'
        'text-decoration:none;box-shadow:0 4px 20px #0004">'
        'Git 변경·정적분석 통합 보고서 ↗</a>\n')
    index = html.lower().rfind('</body>')
    html = html[:index] + anchor + html[index:] if index >= 0 else html + anchor
    static_report.write_text(html, encoding='utf-8')


def generate(repo, output_dir, symbols, graph, *, commits=50):
    """Reuse the *same* static analysis that main.py just generated."""
    from git_insights_cli import analyze_target, write_report
    from analyzer.integration import join_results, write_integrated_report
    from analyzer.git_insights import git

    repo = Path(repo).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()
    if not repo.is_dir():
        raise ValueError('분석 대상이 로컬 폴더가 아닙니다: ' + str(repo))
    try:
        sha = git(repo, 'rev-parse', '--verify', 'HEAD').strip()
    except (OSError, ValueError) as exc:
        raise ValueError('Git 통합 보고서는 .git 이력이 있는 실제 Git clone이 필요합니다. ZIP 다운로드 폴더에는 Git 이력이 없습니다.') from exc
    if symbols.get('commit') != sha or graph.get('commit') != sha:
        raise ValueError('정적분석 결과와 Git HEAD가 동일하지 않습니다. 작업 중 커밋이 바뀌었는지 확인하세요.')
    data = analyze_target(str(repo), max_commits=commits)
    if data['head'] != sha:
        raise ValueError('분석 도중 HEAD가 변경되어 보고서를 생성하지 않았습니다.')
    result = join_results(data, symbols, graph)
    destination = output_dir / 'git_validation'
    write_report(data, destination / 'git')
    write_integrated_report(result, destination)
    add_report_link(output_dir / 'report.html')
    print('[Git Validation] 통합 분석:', destination / 'index.html', flush=True)
    return destination / 'index.html'

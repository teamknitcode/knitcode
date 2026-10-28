"""Compact, read-only Git insights for the existing KnitCode VS Code side panel.

The extension invokes this in isolated Python mode (-I) and consumes JSON stdout.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from analyzer.git_insights import analyze, git


def summarize(root, limit=50):
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('프로젝트 디렉터리 경로가 필요합니다.')
    try:
        top = Path(git(root, 'rev-parse', '--show-toplevel').strip()).resolve()
        if root != top:
            raise ValueError('VS Code에서 Git 저장소의 최상위 폴더를 열어주세요.')
        report = analyze(top, max_commits=limit)
    except (OSError, ValueError) as exc:
        return {'available': False, 'error': str(exc), 'files': {}, 'authors': [], 'head': None}
    file_rows = defaultdict(lambda: {'commits': 0, 'authors': Counter(), 'types': Counter(), 'functions': Counter(), 'cochanges': []})
    for commit in report['commits']:
        for entry in commit['files']:
            name = entry['path']
            row = file_rows[name]
            row['commits'] += 1
            row['authors'][commit['author']] += 1
            row['types'][commit['classification']['type']] += 1
            for change in entry['functions']:
                row['functions'][change['name']] += 1
    for pair in report['pairs']:
        file_rows[pair['a']]['cochanges'].append({'file': pair['b'], 'count': pair['count'],
                                                    'confidence': pair['p_b_given_a']})
        file_rows[pair['b']]['cochanges'].append({'file': pair['a'], 'count': pair['count'],
                                                    'confidence': pair['p_a_given_b']})
    files = {}
    for name, row in file_rows.items():
        files[name] = {
            'commits': row['commits'],
            'authors': [{'name': k, 'count': v} for k,v in row['authors'].most_common(8)],
            'types': dict(row['types']),
            'functions': [{'name': k, 'count': v} for k,v in row['functions'].most_common(12)],
            'cochanges': sorted(row['cochanges'], key=lambda x: -x['count'])[:8],
        }
    return {'available': True, 'head': report['head'],
            'analyzed_commits': len(report['commits']),
            'authors': [{'name': a['names'][0] if a['names'] else a['id'],
                         'commits': a['commits']} for a in report['authors']][:30],
            'files': files, 'warnings': report.get('warnings', []),
            'note': '과거 커밋의 변경 빈도와 공동 변경은 상관관계이며 호출 관계나 오류를 확정하지 않습니다.'}


def main():
    parser = argparse.ArgumentParser(description='KnitCode Git Validation VS Code JSON adapter')
    parser.add_argument('repository')
    parser.add_argument('--commits', type=int, default=50)
    args = parser.parse_args()
    if not 1 <= args.commits <= 300:
        parser.error('--commits는 1~300 범위여야 합니다.')
    print(json.dumps(summarize(args.repository, args.commits), ensure_ascii=True))

if __name__ == '__main__':
    main()

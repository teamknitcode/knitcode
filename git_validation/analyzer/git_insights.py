"""Evidence-based Git history analysis. Never imports or executes target source."""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
from datetime import datetime, timezone
import io
from itertools import combinations
from pathlib import Path
import re
import subprocess
import tokenize


def git(repo, *args, raw=False):
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, timeout=120)
    if result.returncode:
        raise ValueError(result.stderr.decode('utf-8', 'replace').strip())
    return result.stdout if raw else result.stdout.decode('utf-8', 'replace')


def functions(source):
    """Qualified function records; AST counts include nested definitions."""
    if not source:
        return {}
    encoding, _ = tokenize.detect_encoding(io.BytesIO(source).readline)
    text = source.decode(encoding)
    tree = ast.parse(text)
    result = {}

    def visit(node, scope):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = '.'.join(scope + [child.name])
                if not isinstance(child, ast.ClassDef):
                    start = min([child.lineno] + [d.lineno for d in child.decorator_list])
                    calls = sorted({ast.unparse(n.func) for n in ast.walk(child) if isinstance(n, ast.Call)})
                    result[name] = {
                        'signature': ('async ' if isinstance(child, ast.AsyncFunctionDef) else '') +
                        f'{child.name}({ast.unparse(child.args)})' +
                        (f' -> {ast.unparse(child.returns)}' if child.returns else ''),
                        'line': start, 'end_line': child.end_lineno,
                        'ast': ast.dump(child, include_attributes=False),
                        'branches': sum(isinstance(n, (ast.If, ast.IfExp, ast.Match)) for n in ast.walk(child)),
                        'returns': sum(isinstance(n, ast.Return) for n in ast.walk(child)),
                        'raises': sum(isinstance(n, ast.Raise) for n in ast.walk(child)),
                        'calls': calls,
                    }
                visit(child, scope + [child.name])
            else:
                visit(child, scope)
    visit(tree, [])
    return result


def function_changes(before, after):
    old, new = functions(before), functions(after)
    changes = []
    for name in sorted(old.keys() | new.keys()):
        a, b = old.get(name), new.get(name)
        if a and b and a['ast'] == b['ast']:
            continue
        kind = 'added' if a is None else 'deleted' if b is None else 'modified'
        facts = []
        if a and b:
            if a['signature'] != b['signature']:
                facts.append('시그니처 변경')
            for key, label in [('branches', '조건 분기'), ('returns', 'return'), ('raises', 'raise')]:
                if a[key] != b[key]:
                    facts.append(f'{label}: {a[key]} → {b[key]}')
            for key, label in [(set(b['calls']) - set(a['calls']), '호출 추가'),
                               (set(a['calls']) - set(b['calls']), '호출 제거')]:
                if key:
                    facts.append(label + ': ' + ', '.join(sorted(key)))
            if not facts:
                facts.append('본문·상수·데코레이터 등 AST 변경')
        else:
            facts.append('함수 추가' if b else '함수 삭제')
        changes.append({'name': name, 'kind': kind, 'facts': facts,
                        'before': {k: v for k, v in a.items() if k != 'ast'} if a else None,
                        'after': {k: v for k, v in b.items() if k != 'ast'} if b else None})
    return changes


RULES = [
    ('bugfix', r'\b(fix(?:es|ed)?|bug|hotfix|patch)\b|오류|버그|예외|문제 해결'),
    ('feature', r'\b(feat|feature|add(?:ed)?)\b|기능 추가|신규'),
    ('refactor', r'\b(refactor|restructure|cleanup)\b|리팩터|리팩토|구조 개선'),
    ('test', r'\b(tests?|testing)\b|테스트'),
    ('docs', r'\b(docs?|documentation|readme)\b|문서'),
    ('chore', r'\b(chore|build|ci|deps|style|format)\b|의존성|포맷'),
]


def classify(message):
    matches = [{'type': kind, 'matched': match.group(0)} for kind, pattern in RULES
               if (match := re.search(pattern, message, re.I))]
    return {'type': matches[0]['type'] if matches else 'unknown', 'matches': matches,
            'basis': '커밋 메시지 규칙 기반 추정; 실제 수정 목적 또는 해결 성공을 확정하지 않음'}


def changed_files(repo, sha, parent):
    args = ['diff-tree', '--no-commit-id', '-r', '-M', '--name-status', '-z']
    args += [parent, sha] if parent else ['--root', sha]
    tokens = git(repo, *args).split('\0')
    files, i = [], 0
    while i < len(tokens) and tokens[i]:
        status, path = tokens[i], tokens[i + 1]
        i += 2
        old = path
        if status[0] in 'RC':
            path = tokens[i]
            i += 1
        files.append({'status': status, 'path': path, 'old_path': old,
                      'functions': [], 'diagnostics': []})
    return files


def blob(repo, revision, path, limit):
    size = int(git(repo, 'cat-file', '-s', f'{revision}:{path}'))
    if size > limit:
        raise ValueError(f'소스 크기 제한 초과: {size} > {limit} bytes')
    return git(repo, 'show', f'{revision}:{path}', raw=True)


def analyze(repo, *, revision='HEAD', max_commits=500, pair_limit=40,
            source_limit=500_000, diff_limit=30_000, aliases=None, since=None, until=None):
    if min(max_commits, pair_limit, source_limit, diff_limit) < 1:
        raise ValueError('분석 제한값은 모두 1 이상이어야 합니다.')
    repo = Path(repo).resolve()
    # Resolve before using user input in any Git command accepting options.
    head = git(repo, 'rev-parse', '--verify', '--end-of-options', revision + '^{commit}').strip()
    aliases = {k.lower(): v for k, v in (aliases or {}).items()}
    shas = git(repo, 'rev-list', '--topo-order', head).splitlines()
    commits, warnings = [], []
    shallow = git(repo, 'rev-parse', '--is-shallow-repository').strip() == 'true'
    if shallow:
        warnings.append('얕은 clone입니다. 누락된 부모를 최초 커밋으로 오인하지 않도록 경계 커밋의 변경 분석을 생략합니다.')
    if len(shas) < 2:
        warnings.append('커밋이 1개 이하이므로 반복 수정 성향과 파일 동시 변경 관계를 판단할 수 없습니다.')
    shallow_ids = set()
    if shallow:
        shallow_path = git(repo, 'rev-parse', '--git-path', 'shallow').strip()
        p = Path(shallow_path)
        shallow_ids = set((p if p.is_absolute() else repo / p).read_text().splitlines())
    candidates = 0
    for sha in shas:
        raw = git(repo, 'show', '-s', '--format=%P%x00%aN%x00%aE%x00%aI%x00%B', sha)
        parents, name, email, date, message = raw.split('\0', 4)
        if since and date[:10] < since or until and date[:10] > until:
            continue
        candidates += 1
        if len(commits) >= max_commits:
            continue
        parent_list = parents.split()
        parent = parent_list[0] if parent_list else None
        category = classify(message)
        author = aliases.get(email.lower(), email.lower())
        c = {'sha': sha, 'parents': parent_list, 'author': author, 'name': name,
             'email': email, 'date': date, 'message': message.strip(), 'classification': category,
             'files': [], 'pair_eligible': False, 'excluded_reason': None}
        if sha in shallow_ids:
            c['excluded_reason'] = 'shallow_boundary'
        elif len(parent_list) > 1:
            c['excluded_reason'] = 'merge'
        else:
            c['files'] = changed_files(repo, sha, parent)
            if not parent:
                c['excluded_reason'] = 'initial'
            elif len(c['files']) > pair_limit:
                c['excluded_reason'] = 'bulk'
            else:
                c['pair_eligible'] = True
            for f in c['files']:
                status, path, old_path = f['status'][0], f['path'], f['old_path']
                if path.endswith('.py') or old_path.endswith('.py'):
                    try:
                        before = blob(repo, parent, old_path, source_limit) if parent and status != 'A' and old_path.endswith('.py') else b''
                        after = blob(repo, sha, path, source_limit) if status != 'D' and path.endswith('.py') else b''
                        f['functions'] = function_changes(before, after)
                    except (SyntaxError, UnicodeError, LookupError, ValueError, RecursionError) as exc:
                        f['diagnostics'].append(f'함수 비교 불가: {exc}')
                # Bound source reads before requesting potentially enormous patches.
                try:
                    if parent and status != 'A':
                        blob(repo, parent, old_path, source_limit)
                    if status != 'D':
                        blob(repo, sha, path, source_limit)
                    args = ['diff', '--no-ext-diff', '--no-textconv', '--no-color', '--unified=3', parent, sha] if parent else [
                        'show', '--format=', '--no-ext-diff', '--no-textconv', '--no-color', '--unified=3', sha]
                    patch = git(repo, *args, '--', old_path, path)
                    f['diff'] = patch[:diff_limit]
                    f['diff_truncated'] = len(patch) > diff_limit
                except ValueError as exc:
                    f['diff'] = ''
                    f['diagnostics'].append(f'diff 생략: {exc}')
        commits.append(c)
    authors = {}
    frequency, pair_commits = Counter(), defaultdict(list)
    for c in commits:
        a = authors.setdefault(c['author'], {'id': c['author'], 'names': set(), 'emails': set(),
                              'commits': 0, 'types': Counter(), 'files': Counter(), 'folders': Counter(),
                              'functions': Counter(), 'bugfix_commits': []})
        a['names'].add(c['name']); a['emails'].add(c['email']); a['commits'] += 1
        a['types'][c['classification']['type']] += 1
        if c['classification']['type'] == 'bugfix':
            a['bugfix_commits'].append(c['sha'])
        for f in c['files']:
            a['files'][f['path']] += 1
            folder = f['path'].split('/')[0] if '/' in f['path'] else '(root)'
            a['folders'][folder] += 1
            for change in f['functions']:
                a['functions'][f['path'] + '::' + change['name']] += 1
        if c['pair_eligible']:
            paths = sorted({f['path'] for f in c['files']})
            frequency.update(paths)
            for pair in combinations(paths, 2):
                pair_commits[pair].append(c['sha'])
    for a in authors.values():
        a['names'], a['emails'] = sorted(a['names']), sorted(a['emails'])
        for key in ('types', 'files', 'folders', 'functions'):
            a[key] = dict(sorted(a[key].items(), key=lambda x: (-x[1], x[0])))
    pairs = [{'a': a, 'b': b, 'count': len(ids), 'a_changes': frequency[a], 'b_changes': frequency[b],
              'p_b_given_a': len(ids) / frequency[a], 'p_a_given_b': len(ids) / frequency[b],
              'jaccard': len(ids) / (frequency[a] + frequency[b] - len(ids)), 'commits': ids}
             for (a, b), ids in pair_commits.items()]
    pairs.sort(key=lambda p: (-p['count'], -p['jaccard'], p['a'], p['b']))
    return {'schema_version': 'git-insights-1.0', 'repository': repo.name, 'head': head,
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'scope': {'revision': revision, 'reachable_commits': len(shas), 'matching_commits': candidates,
                      'analyzed_commits': len(commits), 'truncated': candidates > max_commits,
                      'since': since, 'until': until, 'date_basis': 'author date (recorded offset)',
                      'max_commits': max_commits, 'pair_limit': pair_limit, 'shallow': shallow,
                      'pair_eligible_commits': sum(c['pair_eligible'] for c in commits),
                      'excluded': dict(Counter(c['excluded_reason'] for c in commits if c['excluded_reason']))},
            'warnings': warnings, 'authors': list(authors.values()), 'pairs': pairs, 'commits': commits,
            'limitations': [
                '작성자 이름·이메일은 Git 메타데이터이며 GitHub 계정 인증 정보가 아닙니다. .mailmap 및 aliases를 적용합니다.',
                '작업 유형·오류 수정 여부는 메시지 규칙 기반 추정입니다. Issue·PR 내용과 수정 성공 여부는 확인하지 않습니다.',
                '동시 변경은 상관관계입니다. 최초·병합·대량 변경 커밋은 분자와 분모 모두에서 제외됩니다.',
                '병합 커밋의 충돌 해결 변경은 분석하지 않습니다. 도달 가능한 일반 커밋은 한 번씩 분석합니다.',
                '함수 비교는 Python AST 대상입니다. 주석·공백 변화는 함수 변경에 포함하지 않습니다. 중첩 함수 변화는 바깥 함수에도 반영됩니다.',
                '함수 이름 변경·이동은 추가/삭제로 나타날 수 있습니다. Git이 탐지한 파일 이름 변경은 커밋 내에서 비교하나 과거 경로 통계는 합치지 않습니다.',
                '폴더 히트맵은 파일 변경 횟수입니다. 한 커밋의 여러 파일이 각각 집계됩니다. 개발자 생산성 점수가 아닙니다.',
                '파일 관계는 Git 동시 변경 기준입니다. 함수의 호출 추가·제거는 구문 비교이며 실제 실행 관계를 보장하지 않습니다.',
            ]}

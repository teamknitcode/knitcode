"""History-only hotspots and explicit, heuristic test evidence."""
import ast
from collections import defaultdict
from pathlib import PurePosixPath
from .git_insights import git, blob


def is_test(path):
    p = PurePosixPath(path)
    return path.endswith('.py') and (p.name.startswith('test_') or p.name.endswith('_test.py') or 'tests' in p.parts or 'test' in p.parts)


def enrich(repo, data, test_limit=200):
    rows = {}
    for c in data['commits']:
        if c['excluded_reason'] in ('initial', 'merge', 'shallow_boundary'):
            continue
        for f in c['files']:
            keys = [('file', f['path'])] + [('function', f['path']+'::'+x['name']) for x in f['functions']]
            for kind, key in keys:
                r = rows.setdefault((kind,key), dict(kind=kind, name=key, commits=[], authors=set(), bugfixes=0))
                if c['sha'] not in r['commits']:
                    r['commits'].append(c['sha']); r['authors'].add(c['author'])
                    r['bugfixes'] += c['classification']['type'] == 'bugfix'
    data['hotspots'] = sorted([dict(r, authors=sorted(r['authors']), count=len(r['commits'])) for r in rows.values()], key=lambda r: (-r['count'], -r['bugfixes'], r['name']))
    # Snapshot candidates are explicitly HEAD/revision-based, not historical coverage.
    paths = [x for x in git(repo, 'ls-tree', '-r', '--name-only', '-z', data['head']).split('\0') if is_test(x)]
    index, diagnostics = [], []
    for path in paths[:test_limit]:
        try:
            tree = ast.parse(blob(repo, data['head'], path, 500000))
            imports = set()
            for n in ast.walk(tree):
                if isinstance(n, ast.Import): imports.update(a.name for a in n.names)
                if isinstance(n, ast.ImportFrom):
                    imports.add(n.module or '')
                    imports.update((n.module+'.' if n.module else '')+a.name for a in n.names)
            index.append((path, imports))
        except (ValueError, SyntaxError, UnicodeError, RecursionError) as exc:
            diagnostics.append({'path':path, 'reason':type(exc).__name__})
    events = []
    for c in data['commits']:
        if c['excluded_reason'] in ('initial','merge','shallow_boundary'): continue
        changed = {f['path'] for f in c['files']}
        changed_tests = sorted(p for p in changed if is_test(p))
        for f in c['files']:
            if not f['path'].endswith('.py') or is_test(f['path']): continue
            module = f['path'][:-3].replace('/', '.')
            if module.startswith('src.'): module=module[4:]
            stem = PurePosixPath(f['path']).stem
            candidates = []
            for path, imports in index:
                evidence=[]
                if any(i == module or i.startswith(module+'.') for i in imports): evidence.append('기준 리비전 AST import 일치')
                if PurePosixPath(path).stem in ('test_'+stem, stem+'_test'): evidence.append('파일명 규칙 일치 · 추정')
                if evidence: candidates.append(dict(path=path, evidence=evidence, changed=path in changed))
            events.append(dict(sha=c['sha'], author=c['author'], path=f['path'], functions=[x['name'] for x in f['functions']],
                               candidates=candidates, changed_tests=changed_tests,
                               related_test_changed=any(x['changed'] for x in candidates)))
    data['test_changes'] = events
    data['test_scope'] = dict(revision=data['head'], total_tests=len(paths), indexed_tests=len(index), limit=test_limit, diagnostics=diagnostics,
        note='관련 테스트는 기준 리비전의 import·파일명 후보입니다. 함수 실행 커버리지나 과거 시점의 연결을 증명하지 않습니다. 같은 커밋의 다른 테스트 변경은 별도로 표시합니다.')

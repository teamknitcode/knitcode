"""Join history keys to snapshot symbols without conflating the two kinds of evidence."""
from collections import defaultdict
import json
from pathlib import Path


def join_results(history, symbols, graph):
    if history['head'] != symbols.get('commit') or history['head'] != graph.get('commit'):
        raise ValueError('Git 분석과 정적분석의 기준 커밋이 다릅니다.')
    by_key = defaultdict(list)
    # Upstream evidence includes the repository directory; Git paths do not.
    prefix = (symbols.get('repository') or '') + '/'
    for symbol in symbols['symbols']:
        if symbol['kind'] in ('FUNCTION', 'METHOD'):
            path = symbol['file'].replace('\\', '/')
            if symbols.get('repository') and path.startswith(prefix):
                path = path[len(prefix):]
            by_key[(path, symbol['qualified_name'])].append(symbol['id'])
    nodes = {n['id']: n for n in graph['nodes']}
    incoming, outgoing = defaultdict(list), defaultdict(list)
    for edge in graph['edges']:
        if edge['type'] == 'CALLS':
            incoming[edge['target']].append(edge)
            outgoing[edge['source']].append(edge)
    events = defaultdict(list)
    for commit in history['commits']:
        for file in commit['files']:
            for change in file['functions']:
                events[(file['path'], change['name'])].append({
                    'sha': commit['sha'], 'author': commit['author'], 'date': commit['date'],
                    'message': commit['message'], 'kind': change['kind'], 'facts': change['facts'],
                    'classification': commit['classification'], 'old_path': file['old_path'],
                    'excluded_reason': commit['excluded_reason'],
                })
    rows = []
    for (file, name), changes in sorted(events.items()):
        candidates = by_key.get((file, name), [])
        selected = candidates[0] if len(candidates) == 1 else None
        counted = [e for e in changes if e['excluded_reason'] not in ('initial', 'merge', 'shallow_boundary')]
        rows.append({
            'file': file, 'name': name, 'symbol_candidates': candidates,
            'match': 'unique_key' if selected else ('ambiguous_key' if candidates else 'unmatched'),
            'change_count': len({e['sha'] for e in counted}),
            'authors': sorted({e['author'] for e in changes}), 'events': changes,
            'callers': incoming.get(selected, []), 'callees': outgoing.get(selected, []),
        })
    return {
        'schema_version': 'knitcode-integration-1.0', 'repository': history['repository'],
        'commit': history['head'], 'source': history['source'], 'scope': history['scope'],
        'summary': {'history_functions': len(rows),
                    'matched_keys': sum(r['match'] == 'unique_key' for r in rows),
                    'ambiguous_keys': sum(r['match'] == 'ambiguous_key' for r in rows),
                    'unmatched_keys': sum(r['match'] == 'unmatched' for r in rows),
                    'static_nodes': len(nodes), 'static_edges': len(graph['edges'])},
        'functions': sorted(rows, key=lambda r: (-r['change_count'], r['file'], r['name'])),
        'nodes': nodes, 'co_changes': history['pairs'],
        'warnings': history['warnings'] + history.get('github', {}).get('warnings', []),
        'limitations': [
            '경로 + 한정 함수명으로 기준 커밋의 심볼 후보를 연결합니다. 과거 함수와 동일한 개체임을 증명하지 않습니다.',
            '호출 관계는 기준 커밋의 정적 추론이며 과거 커밋 시점의 호출 관계가 아닙니다. may-call 등 원본 근거를 유지합니다.',
            '호출자는 직접 호출하는 후보만 표시합니다. 실행 영향 또는 전이 영향 범위를 검증한 결과가 아닙니다.',
            '삭제·이동·이름 변경은 미연결될 수 있습니다. 중복 정의는 임의 선택하지 않습니다.',
            '최초·병합·얕은 clone 경계는 반복 변경 횟수에서 제외합니다. 최초 추가 이벤트는 근거로 표시합니다.',
            '동시 수정은 Git 이력상의 상관관계이며 코드 의존성 간선과 별개입니다.',
            '커밋된 파일만 분석합니다. 로컬 미커밋 변경·심볼릭 링크·서브모듈 내부는 포함하지 않습니다.',
        ],
    }


def write_integrated_report(data, output):
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(data, ensure_ascii=False, indent=2)
    (out / 'integrated_result.json').write_text(serialized, encoding='utf-8')
    template = (Path(__file__).parent / 'templates/integrated.html').read_text(encoding='utf-8')
    safe = serialized.replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    (out / 'index.html').write_text(template.replace('__REPORT_DATA__', safe), encoding='utf-8')

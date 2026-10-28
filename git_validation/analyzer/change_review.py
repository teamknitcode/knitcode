"""Evidence-based revision comparison; no target imports or execution."""
from collections import Counter, defaultdict, deque
from pathlib import Path, PurePosixPath
import json

from analyzer.git_insights import blob, changed_files, function_changes, functions, git
from analyzer.extensions import is_test


def relative_file(path, repository):
    path = path.replace('\\', '/')
    prefix = repository + '/' if repository else ''
    return path[len(prefix):] if prefix and path.startswith(prefix) else path


def function_delta(repo, base, head, source_limit=500_000):
    files = changed_files(repo, head, base)
    for file in files:
        if not any(p.endswith('.py') for p in (file['old_path'], file['path'])):
            continue
        try:
            before = blob(repo, base, file['old_path'], source_limit) if file['status'][0] != 'A' and file['old_path'].endswith('.py') else b''
            after = blob(repo, head, file['path'], source_limit) if file['status'][0] != 'D' and file['path'].endswith('.py') else b''
            file['functions'] = function_changes(before, after)
            if file['old_path'] != file['path']:
                old, new = functions(before), functions(after)
                seen = {f['name'] for f in file['functions']}
                for name in sorted(old.keys() & new.keys() - seen):
                    file['functions'].append({'name': name, 'kind': 'file_renamed',
                        'facts': ['Git이 탐지한 파일 경로 변경; 함수 본문 AST는 동일'],
                        'before': {k: v for k, v in old[name].items() if k != 'ast'},
                        'after': {k: v for k, v in new[name].items() if k != 'ast'}})
        except (ValueError, SyntaxError, UnicodeError, LookupError, RecursionError) as exc:
            file['diagnostics'].append('함수 비교 불가: ' + str(exc))
    return files


def symbol_key(node, repository):
    # Graph nodes use canonical_name; versioned node IDs can include unstable line suffixes.
    return (relative_file(node['file'], repository), node['kind'], node['canonical_name'])


def graph_delta(before, after):
    def collect(graph):
        nodes = {n['id']: n for n in graph['nodes']}
        node_keys = Counter(symbol_key(n, graph.get('repository')) for n in nodes.values())
        relations = defaultdict(list)
        for edge in graph['edges']:
            if edge['source'] not in nodes or edge['target'] not in nodes:
                continue
            key = (symbol_key(nodes[edge['source']], graph.get('repository')),
                   symbol_key(nodes[edge['target']], graph.get('repository')), edge['type'])
            relations[key].append(edge)
        return node_keys, relations
    bn, be = collect(before)
    hn, he = collect(after)
    def node_rows(counter):
        return [{'file': k[0], 'kind': k[1], 'canonical_name': k[2], 'count': count}
                for k, count in sorted(counter.items())]
    def edge_rows(keys, values):
        return [{'source': {'file': key[0][0], 'kind': key[0][1], 'name': key[0][2]},
                 'target': {'file': key[1][0], 'kind': key[1][1], 'name': key[1][2]},
                 'type': key[2], 'evidence': values[key]} for key in sorted(keys)]
    return {'added_symbols': node_rows(hn - bn), 'removed_symbols': node_rows(bn - hn),
            'added_relations': edge_rows(he.keys() - be.keys(), he),
            'removed_relations': edge_rows(be.keys() - he.keys(), be),
            'before_status_summary': before.get('status_summary', {}),
            'after_status_summary': after.get('status_summary', {}),
            'note': '경로·종류·정규 이름 기준 관계 집합 비교. 줄 이동은 새 관계로 세지 않습니다. 같은 관계의 호출 횟수·근거 변경은 별도 비교하지 않습니다. 함수 이동·이름 변경은 추가/삭제로 나타날 수 있습니다.'}


def impact_candidates(files, snapshots, *, max_depth=5, max_nodes=500):
    results = []
    for side, bundle in snapshots.items():
        symbols, graph = bundle['symbols'], bundle['graph']
        nodes = {n['id']: n for n in graph['nodes']}
        by_key, incoming = defaultdict(list), defaultdict(list)
        for sym in symbols['symbols']:
            if sym['kind'] in ('FUNCTION', 'METHOD'):
                by_key[(relative_file(sym['file'], symbols.get('repository')), sym['qualified_name'])].append(sym['id'])
        for edge in graph['edges']:
            if edge['type'] == 'CALLS':
                incoming[edge['target']].append(edge)
        changed_paths = {f['old_path'] if side == 'base' else f['path'] for f in files}
        for file in files:
            for change in file['functions']:
                if change['before' if side == 'base' else 'after'] is None:
                    continue
                path = file['old_path'] if side == 'base' else file['path']
                roots = by_key.get((path, change['name']), [])
                record = {'side': side, 'commit': graph['commit'], 'file': path, 'function': change['name'],
                          'change_kind': change['kind'], 'root_candidates': roots,
                          'ambiguous_root': len(roots) > 1, 'candidates': [],
                          'depth_limited': False, 'node_limited': False}
                # Include all possible definitions explicitly, never silently choose one.
                for root in roots:
                    seen = {root}
                    queue = deque([(root, [])])
                    while queue:
                        target, chain = queue.popleft()
                        for edge in incoming.get(target, []):
                            caller = edge['source']
                            if caller in seen or caller not in nodes:
                                continue
                            if len(chain) >= max_depth:
                                record['depth_limited'] = True
                                continue
                            if len(seen) - 1 >= max_nodes:
                                record['node_limited'] = True
                                continue
                            seen.add(caller)
                            # Path is ordered caller -> ... -> changed function.
                            new_chain = [edge, *chain]
                            node = nodes[caller]
                            caller_path = relative_file(node['file'], graph.get('repository'))
                            record['candidates'].append({'root': root, 'node': node,
                                'file': caller_path, 'distance': len(new_chain), 'path': new_chain,
                                'is_test_file': is_test(caller_path),
                                'file_changed': caller_path in changed_paths,
                                'certainty': '정적 호출 경로 후보; 각 간선의 원본 근거 참조'})
                            queue.append((caller, new_chain))
                results.append(record)
    return results


def recommend_tests(files, impacts, snapshots):
    tests = {}
    def add(side, path, reason):
        row = tests.setdefault((side, path), {'side': side, 'file': path, 'reasons': []})
        if reason not in row['reasons']:
            row['reasons'].append(reason)
    for impact in impacts:
        for candidate in impact['candidates']:
            if candidate['is_test_file']:
                add(impact['side'], candidate['file'], {'type': 'call_path',
                    'changed_function': impact['file'] + '::' + impact['function'],
                    'distance': candidate['distance'], 'path': candidate['path']})
    for side, bundle in snapshots.items():
        symbols, ast_data = bundle['symbols'], bundle['ast']
        repo_name = symbols.get('repository')
        test_paths = {relative_file(f['file'], repo_name) for f in ast_data['files']
                      if is_test(relative_file(f['file'], repo_name))}
        changed = {f['old_path'] if side == 'base' else f['path'] for f in files}
        for path in sorted(test_paths & changed):
            add(side, path, {'type': 'test_file_changed'})
        target_modules = defaultdict(set)
        for symbol in symbols['symbols']:
            path = relative_file(symbol['file'], repo_name)
            if path in changed and not is_test(path):
                target_modules[symbol['module']].add(path)
        for imp in symbols['imports']:
            path = relative_file(imp['file'], repo_name)
            if path not in test_paths:
                continue
            # Only absolute imports here; relative imports require real resolution.
            if imp.get('level', 0):
                continue
            names = {imp.get('imported_module') or '', imp.get('imported_canonical') or ''}
            for module, target_paths in target_modules.items():
                if module and any(name == module or name.startswith(module + '.') for name in names):
                    for target in sorted(target_paths):
                        add(side, path, {'type': 'absolute_import', 'changed_file': target,
                                        'line': imp.get('line')})
        for target in sorted(changed):
            if not target.endswith('.py') or is_test(target):
                continue
            stem = PurePosixPath(target).stem
            for path in sorted(test_paths):
                if PurePosixPath(path).stem in ('test_' + stem, stem + '_test'):
                    add(side, path, {'type': 'filename_heuristic', 'changed_file': target})
    rows = list(tests.values())
    for row in rows:
        row['priority'] = 1 if any(r['type'] == 'call_path' for r in row['reasons']) else 2
        row['commit'] = snapshots[row['side']]['graph']['commit']
    return sorted(rows, key=lambda r: (r['priority'], r['file'], r['side']))


def missing_cochanges(history, files, head_paths, *, min_support=3, min_confidence=0.6):
    changed = {p for f in files for p in (f['old_path'], f['path'])}
    renames = {f['old_path']: f['path'] for f in files if f['status'].startswith('R')}
    recommendations = []
    excluded_absent = 0
    for pair in history['pairs']:
        if pair['count'] < min_support:
            continue
        for source, candidate, confidence, denominator in (
            (pair['a'], pair['b'], pair['p_b_given_a'], pair['a_changes']),
            (pair['b'], pair['a'], pair['p_a_given_b'], pair['b_changes'])):
            if source not in changed or candidate in changed or confidence < min_confidence:
                continue
            if candidate not in head_paths:
                excluded_absent += 1
                continue
            recommendations.append({'changed_file': renames.get(source, source),
                'historical_file': source, 'candidate_file': candidate, 'support': pair['count'],
                'source_change_count': denominator, 'conditional_ratio': confidence,
                'jaccard': pair['jaccard'], 'evidence_commits': pair['commits'],
                'reason': '과거 동시 수정 근거; 이번 변경에 필요한 수정인지 검토 권장'})
    return {'recommendations': sorted(recommendations,
            key=lambda r: (-r['conditional_ratio'], -r['support'], r['candidate_file'])),
            'history_commit': history['head'], 'scope': history['scope'],
            'thresholds': {'min_support': min_support, 'min_confidence': min_confidence},
            'excluded_absent_at_head': excluded_absent,
            'note': '비교 시작 커밋까지의 이력만 사용합니다. 최초·병합·대량 변경·얕은 clone 경계는 기존 Git 규칙에 따라 제외합니다. 표본이 적어 추천이 없을 수 있습니다. 수정 누락이나 결함을 확정하지 않습니다.'}


def build_review(repo, base, head, snapshots, history, *, max_depth=5, max_nodes=500,
                 min_support=3, min_confidence=0.6, source_limit=500_000):
    if history['head'] != base:
        raise ValueError('동시 수정 이력은 반드시 비교 시작 커밋에서 수집해야 합니다.')
    for side, sha in [('base', base), ('head', head)]:
        if any(snapshots[side][part].get('commit') != sha for part in ('ast', 'symbols', 'graph')):
            raise ValueError('정적분석 스냅샷의 커밋이 비교 대상과 다릅니다.')
    files = function_delta(repo, base, head, source_limit)
    impacts = impact_candidates(files, snapshots, max_depth=max_depth, max_nodes=max_nodes)
    head_paths = set(git(repo, 'ls-tree', '-rz', '--name-only', head).split('\0'))
    cochanges = missing_cochanges(history, files, head_paths,
                                  min_support=min_support, min_confidence=min_confidence)
    tests = recommend_tests(files, impacts, snapshots)
    signatures = [{'file': f['path'], 'old_path': f['old_path'], 'name': c['name'],
                   'before': c['before']['signature'], 'after': c['after']['signature']}
                  for f in files for c in f['functions']
                  if c['before'] and c['after'] and c['before']['signature'] != c['after']['signature']]
    structure = graph_delta(snapshots['base']['graph'], snapshots['head']['graph'])
    warnings = list(history['warnings'])
    for side, bundle in snapshots.items():
        for error in bundle['ast']['parse_errors']:
            warnings.append(f"{side} 구문 분석 제외: {error['file']} · {error['message']}")
    for file in files:
        warnings.extend(f"{file['path']}: {d}" for d in file['diagnostics'])
    if any(r['depth_limited'] or r['node_limited'] for r in impacts):
        warnings.append('일부 영향 탐색에 깊이/노드 상한이 적용되었습니다. 영향 후보가 완전하지 않을 수 있습니다.')
    return {'schema_version': 'knitcode-change-review-1.0', 'base': base, 'head': head,
        'files': files, 'signature_changes': signatures, 'structure': structure,
        'impacts': impacts, 'test_candidates': tests, 'cochanges': cochanges,
        'summary': {'changed_files': len(files), 'changed_functions': sum(len(f['functions']) for f in files),
            'signature_changes': len(signatures),
            'impact_files': len({c['file'] for r in impacts for c in r['candidates']}),
            'test_files': len({r['file'] for r in tests}),
            'cochange_candidates': len({r['candidate_file'] for r in cochanges['recommendations']})},
        'limits': {'max_depth': max_depth, 'max_nodes_per_root': max_nodes, 'source_limit': source_limit},
        'warnings': warnings,
        'limitations': [
            '두 커밋의 최종 상태 차이입니다. 비교 구간의 중간 수정 후 되돌림은 순변경에 나타나지 않습니다.',
            '기본값은 HEAD~1 대 HEAD입니다. PR 비교에는 merge-base 옵션과 대상 브랜치를 지정하세요.',
            '함수 변경은 Python AST 기준입니다. 주석·공백만 바뀐 함수는 제외하고 중첩 함수 변경은 바깥 함수에도 반영될 수 있습니다.',
            '파일 경로·한정 함수명으로 심볼 후보를 찾습니다. 함수 이름 변경·이동의 동일성은 추적하지 않습니다.',
            '영향은 CALLS 역방향의 정적 후보입니다. base와 head 경로를 구분하고 may-call 등 원본 근거를 유지합니다. 실제 실행 영향이나 버그를 확정하지 않습니다.',
            '각 시작 심볼에서 후보별 최단 경로 하나만 저장합니다. 다른 경로는 생략하며 순환은 재방문하지 않습니다.',
            'base 시점 테스트는 삭제·이동되었을 수 있습니다. head 시점의 테스트만 현재 실행 대상으로 검토하세요.',
            '테스트 후보는 정적 호출·절대 import·파일명 근거입니다. 실제 실행 커버리지·수집 가능성·테스트 성공을 보장하지 않습니다.',
            '시그니처 변경은 호출부 검토 신호입니다. 인자 호환성이나 타입 오류를 판정하지 않습니다.',
            '모듈 상수·클래스 속성·설정 변경 등 함수 AST 밖의 변경은 함수 기반 영향 탐색에서 빠질 수 있습니다. 파일 목록과 그래프 차이를 함께 확인하세요.',
            '동시 수정은 상관관계이며 검토 권고입니다. 커밋 메시지나 작업 의도가 다르면 함께 수정할 필요가 없을 수 있습니다.',
        ]}


def write_review(data, output):
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, ensure_ascii=False, indent=2)
    (out / 'change_review.json').write_text(raw, encoding='utf-8')
    safe = raw.replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    template = (Path(__file__).parent / 'templates/change_review.html').read_text(encoding='utf-8')
    (out / 'index.html').write_text(template.replace('__REPORT_DATA__', safe), encoding='utf-8')

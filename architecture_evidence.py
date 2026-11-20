"""Conservative Python-source architecture role *hypotheses*.

No imports of the target project, no code execution, no network / LLM.
Evidence from syntax and names is reported separately; neither proves runtime behavior.
The main role is ONE presentation choice, while candidates retain ambiguity.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
from pathlib import Path
import re

MAX_SOURCE_BYTES = 1024 * 1024
MAX_EVIDENCE_PER_ROLE = 8
MAX_GRAPH_EVIDENCE = 4

ROLE_LABELS = {
    'entry': 'Entry · 실행 시작 후보',
    'api': 'Server API · 요청 수신',
    'public_api': 'Public API · 라이브러리 인터페이스',
    'service': 'Service · 기능 처리 후보',
    'processing': 'Implementation · 내부 처리 후보',
    'data': 'Persistence · DB 접근',
    'domain': 'Domain · 데이터 구조/스키마',
    'external': 'External · 외부 통신/연동',
    'ui': 'UI · 사용자 인터페이스',
    'middleware': 'Middleware · 처리 중개',
    'background': 'Background · 예약/작업',
    'config': 'Config · 환경 설정',
    'tests': 'Test · 테스트',
    'utils': 'Utilities · 공통 유틸',
    'core': 'Unclassified · 역할 미확정',
}
# Names never establish a behavioral fact. They receive little weight.
PATH_HINTS = {
    'tests': {'test', 'tests', 'testing', 'fixtures'},
    'middleware': {'middleware', 'middlewares', 'interceptor', 'interceptors'},
    'background': {'worker', 'workers', 'jobs', 'job', 'tasks', 'task', 'scheduler', 'schedulers'},
    'config': {'config', 'configs', 'settings', 'setting'},
    'ui': {'views', 'view', 'ui', 'pages', 'page', 'frontend', 'widgets', 'components'},
    'service': {'service', 'services', 'usecase', 'usecases', 'business'},
    'data': {'db', 'database', 'repository', 'repositories', 'storage', 'persistence'},
    'domain': {'models', 'model', 'schemas', 'schema', 'entities', 'entity', 'dto', 'dtos'},
    'external': {'external', 'integrations', 'integration', 'clients', 'client', 'transports', '_transports', 'adapters', 'adapter'},
    'public_api': {'api', '_api', 'interface', 'interfaces'},
    'utils': {'utils', 'util', 'helpers', 'helper', 'shared', 'common'},
}
WEB_FRAMEWORKS = {'fastapi', 'flask', 'django', 'starlette', 'sanic', 'quart', 'aiohttp.web'}
DB_MODULES = {'sqlite3', 'sqlalchemy', 'psycopg', 'psycopg2', 'pymysql', 'asyncpg', 'peewee', 'django.db', 'pymongo', 'mongoengine', 'motor'}
HTTP_CLIENT_MODULES = {'requests', 'httpx', 'httpcore', 'urllib3', 'urllib.request', 'aiohttp.client', 'boto3', 'botocore'}
UI_MODULES = {'streamlit', 'gradio', 'tkinter', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'nicegui', 'dash'}
BACKGROUND_MODULES = {'celery', 'apscheduler', 'rq', 'schedule'}
CONFIG_MODULES = {'pydantic_settings', 'dotenv', 'dynaconf'}
CALL_TYPES = {'calls', 'instantiates', 'calls_override', 'calls_implicit'}


def _dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted(node.value)
        return f'{prefix}.{node.attr}' if prefix else node.attr
    return ''


def _main_check(node):
    if not isinstance(node, ast.Compare) or len(node.ops) != 1 or not isinstance(node.ops[0], ast.Eq):
        return False
    values = [node.left, *node.comparators]
    return (any(isinstance(v, ast.Name) and v.id == '__name__' for v in values)
            and any(isinstance(v, ast.Constant) and v.value == '__main__' for v in values))


def _path_hint(logical_path):
    parts = logical_path.replace('\\', '/').lower().split('/')
    fname = parts[-1]
    if (fname.startswith('test_') or fname.endswith('_test.py') or
            any(part in ('test', 'tests', 'testing', 'fixtures') for part in parts[:-1])):
        return 'tests', '테스트 전용 파일/디렉터리'
    if fname in ('__main__.py', 'manage.py'):
        return 'entry', 'Python 실행 파일명'
    if fname == 'main.py' or fname.endswith('_cli.py') or fname == 'cli.py':
        return 'entry', '실행 파일명 후보 (실제 시작점 여부 미확정)'
    # Critical: wsgi/asgi means an interface, not necessarily a *server entry*;
    # httpx._transports.asgi.py is a client transport, for example.
    for role, tokens in PATH_HINTS.items():
        for part in parts[:-1]:
            if part in tokens:
                return role, f'디렉터리 이름: {part}/'
    stem = fname[:-3] if fname.endswith('.py') else fname
    stem_tokens = {t for t in re.split(r'[_\-.]+', stem) if t}
    for role, tokens in PATH_HINTS.items():
        if stem in tokens or stem_tokens & tokens:
            return role, f'파일 이름 토큰: {stem}'
    if stem in {'asgi', 'wsgi'}:
        return 'public_api', 'ASGI/WSGI 인터페이스명 (서버 진입점으로 확정하지 않음)'
    return None, None


def _matches(module, prefixes):
    return any(module == p or module.startswith(p + '.') for p in prefixes)


def _file_result(path, logical_path):
    scores = Counter()
    signals = defaultdict(list)
    path_role, path_reason = _path_hint(logical_path)
    test_only = path_role == 'tests'

    def mark(role, points, description, line=1, source='ast', code=None):
        if test_only and role != 'tests':
            return
        scores[role] += points
        if len(signals[role]) < MAX_EVIDENCE_PER_ROLE:
            signals[role].append({'line': int(line or 1), 'source': source,
                                  'description': description, 'code': code or None,
                                  'weight': points})

    if path_role:
        mark(path_role, 2 if path_role != 'tests' else 30, path_reason, source='path')

    def finish(note=None, main_guard=False):
        ranked = sorted(((r, n) for r, n in scores.items() if r != 'core'),
                        key=lambda item: (-item[1], item[0]))
        role, score = ranked[0] if ranked else ('core', 0)
        runner_up = ranked[1][1] if len(ranked) > 1 else 0
        winning_signals = signals.get(role, [])
        has_ast = any(s['source'] == 'ast' for s in winning_signals)
        has_graph = any(s['source'] == 'callgraph' for s in winning_signals)
        basis = ('code' if has_ast else 'callgraph' if has_graph else
                 'path' if winning_signals else 'none')
        margin = score - runner_up
        # Confidence is about strength of *syntax-based evidence*, not measured accuracy.
        confidence = ('high' if has_ast and score >= 9 and margin >= 5 else
                      'medium' if (has_ast or has_graph) and score >= 5 and margin >= 2 else 'low')
        evidence = [f"{s['line']}행: {s['description']}" for s in winning_signals]
        if not evidence:
            evidence = ['코드에서 역할을 결정할 만한 단서 부족']
        if note:
            evidence.append(note)
        return {
            'role': role, 'label': ROLE_LABELS[role], 'score': score,
            'basis': basis, 'confidence': confidence,
            'evidence': evidence[:MAX_EVIDENCE_PER_ROLE + 1],
            'signals': [s for ss in signals.values() for s in ss],
            'alternatives': [{'role': r, 'label': ROLE_LABELS[r], 'score': n,
                              'evidence': [s['description'] for s in signals[r][:3]]}
                             for r, n in ranked[1:4] if n > 0],
            'candidates': [{'role': r, 'score': n} for r, n in ranked[:5]],
            'direct_run_candidate': bool(main_guard),
        }

    try:
        if path.stat().st_size > MAX_SOURCE_BYTES:
            return finish('파일 크기 제한으로 AST 검사 생략')
        tree = ast.parse(path.read_bytes(), filename=str(path))
    except (OSError, ValueError, UnicodeError, SyntaxError) as exc:
        return finish(f'AST 파싱 불가: {type(exc).__name__}')

    imports = set()
    alias_map = {}
    imported_names = defaultdict(set)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
                alias_map[alias.asname or alias.name.split('.')[0]] = alias.name if alias.asname else alias.name.split('.')[0]
        elif isinstance(node, ast.ImportFrom):
            # Relative imports belong to the user's package; do NOT interpret as 3rd-party packages.
            if node.level == 0 and node.module:
                imports.add(node.module)
                for alias in node.names:
                    alias_map[alias.asname or alias.name] = node.module + '.' + alias.name
                    imported_names[node.module].add(alias.name)

    def imported(prefixes):
        return any(_matches(mod, prefixes) for mod in imports)

    def canonical(expr):
        head = expr.split('.')[0]
        return alias_map.get(head, head) + expr[len(head):]

    has_web = imported(WEB_FRAMEWORKS)
    has_db = imported(DB_MODULES)
    has_outbound = imported(HTTP_CLIENT_MODULES)
    has_ui = imported(UI_MODULES)
    has_jobs = imported(BACKGROUND_MODULES)
    if has_ui:
        mark('ui', 7, 'UI 프레임워크 import: ' + ', '.join(sorted(m for m in imports if _matches(m, UI_MODULES))[:3]))
    if has_db:
        mark('data', 6, 'DB 드라이버·ORM import: ' + ', '.join(sorted(m for m in imports if _matches(m, DB_MODULES))[:3]))
    if has_outbound:
        mark('external', 4, 'HTTP/외부 클라이언트·전송 라이브러리 import: ' + ', '.join(sorted(m for m in imports if _matches(m, HTTP_CLIENT_MODULES))[:3]))
    if has_jobs:
        mark('background', 5, '작업 큐·스케줄러 import')
    if imported(CONFIG_MODULES):
        mark('config', 5, '환경설정 라이브러리 import')
    if imported({'pytest', 'unittest'}):
        mark('tests', 5, '테스트 프레임워크 import')
    if has_web:
        # Import alone is weak: a model/utility in a web project isn't an API handler.
        mark('api', 1, '서버 웹 프레임워크 import (라우트 여부 별도 확인)')

    direct_run_candidate = False
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _main_check(node.test):
            direct_run_candidate = True
            if path_role == 'entry':
                mark('entry', 9, '__name__ == "__main__" 실행 블록', node.lineno)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                ref = canonical(_dotted(decorator.func if isinstance(decorator, ast.Call) else decorator))
                leaf = ref.rsplit('.', 1)[-1]
                if has_web and leaf in {'route', 'get', 'post', 'put', 'patch', 'delete', 'websocket', 'api_view'}:
                    mark('api', 11, f'웹 요청 핸들러 데코레이터 @{ref}', node.lineno)
                if has_web and leaf == 'middleware':
                    mark('middleware', 10, f'서버 미들웨어 데코레이터 @{ref}', node.lineno)
                if has_jobs and leaf in {'task', 'shared_task'}:
                    mark('background', 10, f'백그라운드 태스크 데코레이터 @{ref}', node.lineno)
        elif isinstance(node, ast.ClassDef):
            bases = {canonical(_dotted(base)).rsplit('.', 1)[-1] for base in node.bases}
            if 'BaseHTTPMiddleware' in bases and has_web:
                mark('middleware', 11, 'HTTP 미들웨어 기반 클래스 상속', node.lineno)
            if has_db and bases & {'DeclarativeBase', 'SQLModel', 'Model', 'Document'}:
                mark('data', 9, 'ORM 모델 또는 Document 클래스 상속', node.lineno)
            if bases & {'BaseModel', 'BaseSettings'} and not has_db:
                mark('domain', 7, 'Pydantic 데이터 모델 / 설정 스키마 클래스', node.lineno)
            if bases & {'BaseSettings'}:
                mark('config', 8, 'BaseSettings 상속', node.lineno)
        elif isinstance(node, ast.Call):
            raw = _dotted(node.func)
            if not raw:
                continue
            resolved = canonical(raw)
            tail = resolved.rsplit('.', 1)[-1]
            if has_web and (resolved in {'fastapi.FastAPI', 'fastapi.APIRouter', 'flask.Flask', 'flask.Blueprint'}):
                mark('api', 9, f'웹 앱/라우터 생성: {raw}()', node.lineno)
            if has_db and tail in {'execute', 'executemany', 'commit', 'rollback', 'cursor', 'create_engine', 'sessionmaker', 'connect'}:
                mark('data', 4, f'DB 라이브러리 사용 맥락의 {raw}() 호출 후보', node.lineno)
            if _matches(resolved, HTTP_CLIENT_MODULES) and tail in {'get', 'post', 'put', 'delete', 'patch', 'request', 'urlopen', 'ClientSession', 'Client', 'Session', 'PoolManager', 'HTTPConnectionPool', 'client', 'resource'}:
                mark('external', 8, f'외부 HTTP/SDK 클라이언트 API 호출 후보: {raw}()', node.lineno)
            if has_jobs and _matches(resolved, BACKGROUND_MODULES) and tail in {'every', 'add_job', 'apply_async', 'delay', 'enqueue'}:
                mark('background', 7, f'스케줄·작업 제출: {raw}()', node.lineno)
            if resolved in {'asyncio.create_task', 'asyncio.ensure_future'}:
                mark('background', 3, f'비동기 태스크 생성: {raw}()', node.lineno)
            if resolved in {'os.getenv', 'dotenv.load_dotenv'}:
                mark('config', 3, f'환경설정 조회: {raw}()', node.lineno)
            if resolved in {'uvicorn.run', 'hypercorn.asyncio.serve'} and not test_only:
                mark('entry', 7, f'서버 실행 호출 후보: {raw}()', node.lineno)

    # A file named api.py is not automatically a server endpoint (requests/api.py).
    # Present library API as its own role unless actual route/handler evidence is found.
    if path_role == 'public_api':
        mark('public_api', 2, '외부에 공개된 인터페이스일 가능성 (이름 기반)', source='path')
    # Data model objects (HTTP requests, OpenAPI schemas) are not DB persistence.
    if path_role == 'domain' and not has_db:
        mark('domain', 2, 'DB 사용 증거가 없는 데이터 구조 파일 (이름 기반)', source='path')
    if direct_run_candidate and not test_only:
        # Metadata only; a __main__ guard is not enough to label the whole file as app entry.
        pass
    return finish(main_guard=direct_run_candidate)


def _fallback(note):
    return {'role':'core', 'label':ROLE_LABELS['core'], 'score':0, 'basis':'none',
            'confidence':'low', 'evidence':[note], 'signals': [],
            'alternatives': [], 'candidates': [], 'direct_run_candidate':False}


def analyze_architecture(root, relative_files):
    """Classify source files with bounded AST scanning. Keys are root-relative paths."""
    root = Path(root).resolve()
    results = {}
    for name in sorted(set(relative_files)):
        if not isinstance(name, str) or not name.endswith('.py'):
            continue
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            continue
        try:
            results[name] = _file_result(path, name)
        except (OSError, ValueError) as exc:
            results[name] = _fallback('AST 분석 실패: ' + type(exc).__name__)
    return results


def architecture_call_context(roles, nodes, edges):
    """Annotate *confirmed graph edges* as evidence, without inventing calls.

    This step does NOT relabel files on topology alone. Example: API -> file does
    not prove that the destination implements business logic. UI displays this as
    supporting context, separately from role classification evidence.
    """
    id_to_file = {n['id']: n.get('file') for n in nodes if 'id' in n}
    context = defaultdict(lambda: {'inbound_files': set(), 'outbound_files': set(),
                                   'incoming_roles': Counter(), 'outgoing_roles': Counter(), 'examples': []})
    seen = set()
    for edge in edges:
        if edge.get('type') not in CALL_TYPES:
            continue
        src, dst = edge.get('source'), edge.get('target')
        sf, tf = id_to_file.get(src), id_to_file.get(dst)
        if not sf or not tf or sf == tf or sf not in roles or tf not in roles:
            continue
        key = (src, dst, edge.get('type'))
        if key in seen:
            continue
        seen.add(key)
        a, b = context[sf], context[tf]
        a['outbound_files'].add(tf)
        b['inbound_files'].add(sf)
        a['outgoing_roles'][roles[tf]['role']] += 1
        b['incoming_roles'][roles[sf]['role']] += 1
        if len(a['examples']) < MAX_GRAPH_EVIDENCE:
            a['examples'].append({'direction':'outgoing', 'from':sf, 'to':tf,
                                  'source_id':src, 'target_id':dst})
        if len(b['examples']) < MAX_GRAPH_EVIDENCE:
            b['examples'].append({'direction':'incoming', 'from':sf, 'to':tf,
                                  'source_id':src, 'target_id':dst})
    for name, role in roles.items():
        item = context.get(name)
        # A function-level call graph can support a *processing hypothesis*:
        # something called from an interface and calling data/external code.
        # This is NOT proof of business semantics, execution, or a request sequence.
        if (item and role['role'] == 'core' and
                any(item['incoming_roles'][k] for k in ('api','public_api','entry')) and
                any(item['outgoing_roles'][k] for k in ('data','external','domain'))):
            role.update({'role':'processing', 'label':ROLE_LABELS['processing'],
                         'score':3, 'basis':'callgraph', 'confidence':'low',
                         'evidence':['호출 그래프에서 인터페이스 측 호출을 받고 다른 계층으로 호출하는 중간 위치 (기능 의미는 미확정)']})
        role['call_context'] = ({'inbound_files':len(item['inbound_files']),
                                 'outbound_files':len(item['outbound_files']),
                                 'incoming_roles': dict(item['incoming_roles']),
                                 'outgoing_roles': dict(item['outgoing_roles']),
                                 'examples': item['examples']}
                                if item else {'inbound_files':0,'outbound_files':0,
                                              'incoming_roles':{},'outgoing_roles':{},'examples':[]})
    return roles

"""Evidence-preserving, symbol-level architecture hypotheses for the KnitCode B view.

No target imports or code execution. Classification is intentionally conservative:
- explicit AST actions are evidence for *technical operations*, not entire-file semantics;
- lexical capability names are labeled as hints, never observed actions;
- each function/class can be grouped independently, including single-file projects;
- all cross-group links come from existing static call edges, never invented flows.

This module does not change the original call-graph or value-flow computation.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
from pathlib import Path
import re

from architecture_evidence import (_dotted, _main_check, _matches, WEB_FRAMEWORKS,
                                   HTTP_CLIENT_MODULES, DB_MODULES, UI_MODULES,
                                   BACKGROUND_MODULES, CALL_TYPES)

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_LINK_EVIDENCE = 15

# Layers are a *presentation* convention, never proof of execution ordering.
LAYERS = {
    'interface': '진입·인터페이스',
    'core': '핵심 기능',
    'integration': '외부·인프라 연동',
    'state': '데이터·상태',
    'output': '표현·출력',
    'support': '설정·지원',
    'unknown': '확인 필요',
}

# Generic capabilities, not repository-specific hardcoding. Name-based signals
# only yield a lexical hint. A project may have none of these capabilities.
CAPABILITIES = {
    'setup': ('앱 구성·초기화', 'interface', ('create_app', 'init_app', 'configure_app', 'setup_app', 'register_blueprint')),
    'cli': ('명령행 인터페이스', 'interface', ('main', 'parse_args', 'cli', 'command', 'handle_command', 'run_cli')),
    'server': ('웹 요청 처리', 'interface', ('route', 'endpoint', 'http_handler', 'login', 'register')),
    'public_api': ('공개 라이브러리 API', 'interface', ('api', 'get', 'post', 'request', 'open_tunnel')),
    'auth': ('인증·권한', 'core', ('authenticate', 'authorize', 'login', 'logout', 'register', 'load_logged_in_user', 'check_password')),
    'enumeration': ('정보 검색·열거', 'core', ('enumerate', 'enumerator', 'enumrator', 'subdomain', 'subbrute', 'search_engine', 'dnsdumpster', 'netcraft', 'googleenum', 'bingenum')),
    'recording': ('녹화·수집', 'core', ('record', 'recorder', 'capture', 'asciicast')),
    'playback': ('재생·복원', 'core', ('play', 'playback', 'replay')),
    'scheduling': ('작업 예약·실행', 'core', ('scheduler', 'schedule_next_run', 'run_pending', 'run_all', 'job')),
    'sql_lexing': ('SQL 토큰화', 'core', ('lexer', 'tokenize', 'tokenizer', 'get_tokens')),
    'sql_grouping': ('SQL 구문 구조화', 'core', ('group_tokens', 'grouping', 'group_matching', 'group_parenthesis', 'group_identifier', 'statement_splitter')),
    'parsing': ('구문 파싱·검증', 'core', ('parse', 'parser', 'parse_sql', 'validate', 'split', 'parse_url')),
    'url_components': ('URL 구성요소 조작', 'core', ('urlsplit', 'urljoin', 'query', 'fragment', 'path', 'furl', 'add_query_param')),
    'text_processing': ('텍스트 분절·전처리', 'core', ('segmentation', 'segment', 'tokenize_text', 'clean_text', 'preprocess')),
    'ranking': ('키워드·문장 순위', 'core', ('textrank', 'rank', 'keyword', 'sentence', 'pagerank')),
    'path_matching': ('경로 탐색·매칭', 'core', ('match_fuzzy', 'match_path', 'autojump', 'find_paths', 'path_match')),
    'face_detection': ('얼굴 검출·전처리', 'core', ('detect_faces', 'face_detector', 'extract_face', 'preprocess_input')),
    'ml_training': ('모델 학습', 'core', ('train', 'fit_model', 'train_model', 'training', 'compile_model')),
    'ml_inference': ('모델 추론', 'core', ('predict', 'classify', 'inference', 'infer', 'process_image')),
    'monitoring': ('시스템 지표 수집', 'core', ('collect_cpu', 'collect_mem', 'collect_net', 'collect_proc', 'cpu_collector', 'mem_collector', 'proc_collector')),
    'orchestration': ('업무·실행 흐름 조정', 'core', ('execute', 'process', 'handle', 'run', 'dispatch', 'workflow', 'run_task')),
    'ssh': ('SSH 연결·세션', 'integration', ('ssh', 'sshclient', 'sshconnection', 'connection_open', 'sshtunnelforwarder', 'connect_ssh')),
    'transfer': ('원격 파일 전송', 'integration', ('transfer', 'upload', 'download', 'put', 'get_remote', 'send_file')),
    'tunnel': ('포트 포워딩·터널', 'integration', ('tunnel', 'forwarder', 'forwardhandler', 'port_forward', 'forward_local')),
    'http_client': ('HTTP 요청·외부 서비스', 'integration', ('send_req', 'send_request', 'fetch_url', 'http_adapter')),
    'database': ('데이터베이스 접근', 'state', ('get_db', 'init_db', 'db_connect', 'db_session', 'execute_query', 'save_to_db')),
    'file_io': ('로컬 파일 입출력', 'state', ('read_file', 'write_file', 'load', 'save', 'read_resource', 'write_resource')),
    'input': ('입력·리소스 읽기', 'interface', ('read_resource', 'read_input', 'read_stdin', 'load_input')),
    'history': ('상태·이력 관리', 'state', ('history', 'visit', 'frequency', 'increment_path', 'load_history', 'save_history')),
    'data_model': ('데이터 모델·구조', 'state', ('model', 'schema', 'dataclass', 'response', 'request_model')),
    'formatting': ('결과 포맷팅', 'output', ('formatter', 'format', 'reformat', 'format_sql', 'pretty_print')),
    'rendering': ('UI·렌더링', 'output', ('render', 'draw', 'display', 'screen', 'console', 'pager', 'paint')),
    'config': ('설정·구성', 'support', ('config', 'settings', 'load_config', 'parse_config')),
    'utility': ('공통 지원', 'support', ('utils', 'helpers', 'helper', 'normalize', 'sanitize')),
    'test': ('테스트·검증', 'support', ('test', 'fixture', 'assert')),
}

# Priorities resolve ties deterministically. They do not imply empirical confidence.
STRONG_PRIORITY = ('server', 'database', 'ssh', 'tunnel', 'transfer', 'ml_training', 'ml_inference',
                   'sql_lexing', 'sql_grouping', 'http_client', 'rendering', 'monitoring', 'scheduling',
                   'setup', 'recording', 'playback', 'face_detection', 'file_io', 'public_api')
ROLE_ORDER = {role: i for i, role in enumerate(STRONG_PRIORITY)}
TECHNICAL_NAMES = {'network_http', 'database_sql', 'local_files', 'ssh_transport', 'terminal_ui',
                   'web_route', 'scheduler', 'model_training', 'model_inference', 'system_metrics'}


def is_test(path):
    p = path.lower().replace('\\', '/')
    name = p.rsplit('/', 1)[-1]
    return (name.startswith('test_') or name.endswith('_test.py') or
            any(seg in {'tests', 'test', 'testing', 'fixtures', 'testdata'} for seg in p.split('/')[:-1]))


def tokens(text):
    """Separate snake case, CamelCase, and digits without substring matching."""
    text = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', str(text))
    return [x for x in re.split(r'[^A-Za-z0-9]+', text.lower()) if x]


def _lexical_capability(name, file_name):
    """Use exact names and complete tokens; avoid 'url' => HTTP or 'sql' => DB."""
    name = name.rsplit('.', 1)[-1].lower()
    components = set(tokens(name))
    # Substantial parts of methods are evidence of the symbol's *name*, nothing more.
    scored = []
    for cap, (_, _, hints) in CAPABILITIES.items():
        best = 0
        for hint in hints:
            ht = tokens(hint)
            if name == hint: best = max(best, 4)
            elif len(ht) >= 2 and all(w in components for w in ht): best = max(best, 3)
            elif len(ht) == 1 and ht[0] in components and len(ht[0]) >= 4: best = max(best, 2)
        if best: scored.append((cap, best))
    # Module names may be a weak fallback when an otherwise meaningless method appears.
    if not scored:
        stem = Path(file_name).stem
        if stem not in {'__init__', '__main__', 'core', 'main', 'utils'}:
            words = set(tokens(stem))
            for cap, (_, _, hints) in CAPABILITIES.items():
                if any(len(h) > 3 and h in words for h in hints if '_' not in h):
                    scored.append((cap, 1))
    return sorted(scored, key=lambda x: (-x[1], ROLE_ORDER.get(x[0], 100), x[0]))


def _scan_one(root, rel):
    path = (root / rel).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        return None
    try:
        tree = ast.parse(path.read_bytes(), filename=str(path))
    except (SyntaxError, UnicodeError, OSError, ValueError):
        return None
    aliases = {}
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imports.add(a.name)
                aliases[a.asname or a.name.split('.')[0]] = a.name if a.asname else a.name.split('.')[0]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module)
            for a in node.names:
                aliases[a.asname or a.name] = node.module + '.' + a.name

    def resolved(node):
        raw = _dotted(node)
        head = raw.split('.')[0]
        return aliases.get(head, head) + raw[len(head):] if raw else ''

    def has(prefixes):
        return any(_matches(mod, prefixes) for mod in imports)

    has_web = has(WEB_FRAMEWORKS)
    has_db = has(DB_MODULES)
    has_ssh = has({'paramiko', 'asyncssh', 'fabric', 'invoke'})
    has_monitor = has({'psutil'})
    has_ml = has({'keras', 'tensorflow', 'torch', 'sklearn', 'cv2', 'face_recognition'})
    has_ui = has(UI_MODULES | {'curses', 'rich', 'urwid', 'blessed'})
    has_job = has(BACKGROUND_MODULES)
    has_sqlparse = has({'sqlparse'})
    file_is_test = is_test(rel)
    symbols = []
    main_guard = any(isinstance(x, ast.If) and _main_check(x.test) for x in tree.body)

    def analyze_symbol(node, owners):
        # Use direct children, not ast.walk(node), so nested functions do not inherit
        # every call from their enclosing function. Code within nested control blocks
        # belongs to its closest function, but definitions are separate symbols.
        name = '.'.join([*owners, node.name])
        lexical = _lexical_capability(node.name, rel)
        ranking = Counter({k: v for k, v in lexical})
        evidence = defaultdict(list)
        facets = set()
        # Class-scoped methods inherit only a weak *name context* from the
        # containing class. This is essential for single-file multi-class code.
        if owners and not file_is_test:
            for cap, score in _lexical_capability(owners[-1], rel):
                if cap in {'enumeration','tunnel','ssh','sql_lexing','sql_grouping','url_components',
                           'ranking','recording','playback','monitoring','rendering','ml_training',
                           'ml_inference','transfer','path_matching','scheduling','face_detection'}:
                    ranking[cap] += min(4, score)
                    evidence[cap].append({'kind':'owner_name_hint','line':node.lineno,
                                          'detail':f'{owners[-1]} 클래스 소속 단서','weight':min(4,score)})
        for cap, score in lexical:
            evidence[cap].append({'kind':'name_hint','line':node.lineno,'detail':f'{name} 이름 단서', 'weight':score})
        def add(cap, pts, kind, desc, line, facet=None):
            # once per AST category and operation: avoid volume-based inflation
            if not any(e['kind']==kind and e['detail']==desc for e in evidence[cap]):
                ranking[cap] += pts
                evidence[cap].append({'kind':kind,'line':line,'detail':desc,'weight':pts})
            if facet: facets.add(facet)
        if file_is_test:
            add('test', 100, 'source_path', '테스트 경로', node.lineno)
        else:
            if node.name in {'create_app', 'init_app', 'configure_app'}:
                add('setup', 7, 'name_context', '앱 구성 함수 명칭', node.lineno)
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    base_name = resolved(base)
                    if base_name.rsplit('.',1)[-1] in {'BaseRequestHandler', 'StreamRequestHandler'}:
                        add('tunnel' if has_ssh else 'server', 8, 'class_base', f'요청 처리 기반 클래스 {base_name}', node.lineno)
                    if base_name.rsplit('.',1)[-1] in {'BaseModel', 'SQLModel', 'DeclarativeBase'}:
                        add('data_model', 8, 'class_base', f'모델 기반 클래스 {base_name}', node.lineno)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for d in node.decorator_list:
                    name_dec = resolved(d.func if isinstance(d, ast.Call) else d)
                    tail = name_dec.rsplit('.',1)[-1]
                    if has_web and tail in {'route','get','post','put','patch','delete','websocket','api_view'}:
                        add('server', 15, 'web_decorator', f'웹 라우트 @{name_dec}', node.lineno, 'web_route')
                    elif tail in {'command','group'} and (has({'click', 'typer'}) or 'cli' in name_dec):
                        add('cli', 12, 'cli_decorator', f'CLI 명령 @{name_dec}', node.lineno)
                    elif has_job and tail in {'task','shared_task'}:
                        add('scheduling', 12, 'task_decorator', f'작업 선언 @{name_dec}', node.lineno, 'scheduler')
        class CallFinder(ast.NodeVisitor):
            def __init__(self): self.calls=[]
            def visit_Call(self, item):
                self.calls.append(item)
                self.generic_visit(item)
            def visit_FunctionDef(self, item): pass
            visit_AsyncFunctionDef = visit_FunctionDef
            def visit_ClassDef(self, item): pass
            def visit_Lambda(self, item): pass
        finder = CallFinder()
        for item in node.body:
            finder.visit(item)
        if not file_is_test:
            for c in finder.calls:
                call = resolved(c.func)
                tail = call.rsplit('.', 1)[-1]
                if _matches(call, HTTP_CLIENT_MODULES) and tail in {'get','post','put','patch','delete','request','urlopen','send','Client','Session','ClientSession'}:
                    add('http_client', 11, 'http_call', f'HTTP 클라이언트 {call}()', c.lineno, 'network_http')
                if has_db and (call.startswith(('sqlite3.', 'sqlalchemy.', 'psycopg', 'pymongo.', 'pymysql.')) or tail in {'execute', 'executemany', 'commit', 'rollback', 'create_engine', 'cursor'}):
                    add('database', 9, 'db_call', f'DB 사용 맥락 {call}()', c.lineno, 'database_sql')
                if has_ssh and (call.startswith(('paramiko.', 'asyncssh.')) or tail in {'connect','open_sftp','exec_command'}):
                    add('ssh', 8, 'ssh_call', f'SSH API 후보 {call}()', c.lineno, 'ssh_transport')
                if call.startswith('psutil.') and has_monitor:
                    add('monitoring', 9, 'system_call', f'시스템 메트릭 {call}()', c.lineno, 'system_metrics')
                if has_ui and (call.startswith(('curses.', 'rich.')) or tail in {'render','draw','print_at','refresh'}):
                    add('rendering', 8, 'ui_call', f'UI API {call}()', c.lineno, 'terminal_ui')
                if has_ml and tail in {'fit','fit_generator','compile','train_on_batch'}:
                    add('ml_training', 9, 'ml_train_call', f'학습 API 후보 {call}()', c.lineno, 'model_training')
                if has_ml and tail in {'predict','predict_proba','detectMultiScale'}:
                    add('ml_inference', 9, 'ml_infer_call', f'추론 API 후보 {call}()', c.lineno, 'model_inference')
                if has_job and tail in {'enqueue','add_job','apply_async','delay','every'}:
                    add('scheduling', 8, 'job_call', f'작업 예약 호출 {call}()', c.lineno, 'scheduler')
                if call in {'builtins.open', 'open'} or call.endswith(('.read_text', '.write_text', '.read_bytes', '.write_bytes')):
                    # I/O alone is NOT a database. This is only an operational facet.
                    add('file_io', 5, 'file_call', f'로컬 파일 API {call}()', c.lineno, 'local_files')
                if has_sqlparse and call.startswith('sqlparse.') and tail in {'parse','split','format'}:
                    add('parsing' if tail != 'format' else 'formatting', 8, 'parser_call', f'파서 API {call}()', c.lineno)
        if not ranking:
            ranking['unclassified'] = 0
        # A semantic function name may describe primary purpose when HTTP/file
        # transport is only one detail of the function.
        for semantic, _ in lexical:
            if semantic in {'recording','playback','parsing','formatting','url_components','auth',
                            'enumeration','path_matching','history','input','ml_training','ml_inference',
                            'sql_grouping','sql_lexing','text_processing','ranking','orchestration','setup'}:
                if ranking.get(semantic, 0) >= 3 and ranking.get('http_client', 0) > 0:
                    ranking[semantic] += 10
                if ranking.get(semantic, 0) >= 3 and ranking.get('file_io', 0) > 0:
                    ranking[semantic] += 5
        # Functional class context can outrank a low-level transport operation,
        # but remains marked as a *lexical* hypothesis.
        if owners and ranking.get('http_client',0):
            for cap in {'enumeration','recording','playback','transfer','ranking'}:
                if any(e['kind']=='owner_name_hint' for e in evidence.get(cap, [])):
                    ranking[cap] += 12
        candidates = sorted(ranking, key=lambda r: (-ranking[r], ROLE_ORDER.get(r,100), r))
        primary = candidates[0]
        if primary == 'unclassified' or ranking[primary] <= 1:
            primary = 'unclassified'
        strong = any(e['kind'] in {'http_call','db_call','ssh_call','web_decorator','cli_decorator',
                    'task_decorator','class_base','system_call','ui_call','ml_train_call','ml_infer_call','parser_call'}
                    for e in evidence[primary])
        basis = 'ast' if strong else ('mixed' if any(e['kind'] in {'file_call','name_context'} for e in evidence[primary])
                    else 'name' if primary!='unclassified' else 'none')
        return {'name': name, 'file': rel, 'line': node.lineno,
                'kind': 'class' if isinstance(node, ast.ClassDef) else 'function',
                'primary': primary, 'label': CAPABILITIES.get(primary,('분류 보류',))[0],
                'layer': CAPABILITIES.get(primary,('', 'unknown'))[1],
                'basis': basis,
                'confidence': 'code' if strong else 'tentative' if primary!='unclassified' else 'unknown',
                'facets': sorted(facets), 'candidates': [{'role':r, 'score':ranking[r]} for r in candidates[:5]],
                'evidence': evidence.get(primary, [])[:6],
                'other_evidence': [dict(capability=r, evidence=evidence[r][:2]) for r in candidates[1:4]]}

    def walk_members(body, owners=()):
        for item in body:
            if isinstance(item, (ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)):
                symbols.append(analyze_symbol(item, owners))
                # Nested functions and class methods are distinct entities.
                walk_members(item.body, (*owners,item.name))
    walk_members(tree.body)
    return {'symbols': symbols, 'imports': imports, 'has_main_guard': main_guard, 'test':file_is_test}


def _match_symbol(node, index):
    file = node.get('file')
    line = node.get('lineno', node.get('line'))
    matches = index.get((file, line), [])
    if len(matches) == 1: return matches[0]
    name = str(node.get('canonical_name') or node.get('name') or '').split('.')[-1]
    exact = [s for s in matches if s['name'].split('.')[-1] == name]
    return exact[0] if len(exact)==1 else None


def _project_profile(counts, evidence):
    """A description based on observed capabilities, not a forced app archetype."""
    if counts['server'] >= 2: name='웹 서버·API 중심'
    elif counts['ml_training'] or counts['ml_inference']: name='머신러닝·추론 중심'
    elif counts['sql_lexing'] or counts['sql_grouping']: name='SQL 파싱 라이브러리'
    elif counts['ssh'] or counts['tunnel']: name='원격 연결·통신 도구'
    elif counts['recording'] or counts['playback']: name='녹화·재생 도구'
    elif counts['enumeration']: name='검색·열거 도구'
    elif counts['url_components']: name='URL 처리 라이브러리'
    elif counts['monitoring']: name='시스템 모니터링 도구'
    elif counts['text_processing'] or counts['ranking']: name='텍스트 처리 라이브러리'
    elif counts['rendering']: name='출력·렌더링 도구'
    elif counts['cli']: name='명령행 도구'
    elif counts['public_api']: name='라이브러리'
    else: name='일반 Python 프로젝트 · 세부 유형 미확정'
    return {'label':name, 'basis':'AST·심볼 이름 기반 후보',
            'evidence':evidence[:6], 'verified':False}


def build_architecture_hierarchy(root, relative_files, nodes, edges):
    """Return JSON-ready role groups and traceable cross-group links.

    A group is not an execution stage and cross-group links are static candidates.
    A single file can contribute *different symbols* to multiple groups.
    """
    root = Path(root).resolve()
    file_results = {}
    index = defaultdict(list)
    for f in sorted(set(relative_files)):
        if not isinstance(f,str) or not f.endswith('.py'): continue
        try: result = _scan_one(root,f)
        except (OSError, ValueError): result = None
        if result is None: continue
        file_results[f] = result
        for s in result['symbols']:
            index[(f,s['line'])].append(s)

    node_map = {n['id']:n for n in nodes if 'id' in n}
    symbol_map = {}
    by_role = defaultdict(list)
    uncertain=[]
    count=Counter()
    for n in nodes:
        if n.get('type') not in {'function','method','class'}: continue
        s=_match_symbol(n,index)
        if not s: continue
        sym={**s, 'id':n['id'], 'file':n.get('file',s['file']), 'lineno':n.get('lineno',s['line'])}
        symbol_map[n['id']]=sym
        if sym['primary']=='unclassified':
            uncertain.append(n['id']);continue
        by_role[sym['primary']].append(n['id'])
        if not is_test(sym['file']): count[sym['primary']] += 1

    groups=[]
    for role, ids in sorted(by_role.items(), key=lambda item:
                            (list(LAYERS).index(CAPABILITIES[item[0]][1]),-len(item[1]),item[0])):
        ids=sorted(set(ids))
        files=sorted({symbol_map[i]['file'] for i in ids})
        examples=[dict(id=i, name=symbol_map[i]['name'], file=symbol_map[i]['file'],
                       line=symbol_map[i]['line'], evidence=symbol_map[i]['evidence'][:2]) for i in ids[:12]]
        code=sum(symbol_map[i]['confidence']=='code' for i in ids)
        groups.append({'id':'cap:'+role, 'role':role, 'name':CAPABILITIES[role][0],
                       'layer':CAPABILITIES[role][1], 'layer_name':LAYERS[CAPABILITIES[role][1]],
                       'description':'함수·클래스별 역할 후보 · 명확한 AST 근거와 명칭 단서를 구분',
                       'function_ids':ids, 'files':files, 'symbol_count':len(ids),
                       'code_evidence_count':code, 'name_hint_count':len(ids)-code,
                       'test':all(is_test(f) for f in files), 'examples':examples})

    membership = {i:g['id'] for g in groups for i in g['function_ids']}
    edge_map={}
    dedup=set()
    for e in edges:
        if e.get('type') not in CALL_TYPES:continue
        a=e.get('source'); b=e.get('target')
        ga=membership.get(a);gb=membership.get(b)
        if not ga or not gb or ga==gb:continue
        # distinct call sites at same source-target may have different line/call_id
        evidence=e.get('evidence') or {}
        site=(a,b,e.get('type'),evidence.get('call_id') or e.get('lineno'))
        if site in dedup:continue
        dedup.add(site)
        key=(ga,gb)
        if key not in edge_map:
            edge_map[key]={'source_group':ga,'target_group':gb,'count':0,'implicit':0,'evidence':[]}
        link=edge_map[key];link['count']+=1
        if e['type']=='calls_implicit':link['implicit']+=1
        if len(link['evidence'])<MAX_LINK_EVIDENCE:
            link['evidence'].append({'source':a,'target':b,'type':e['type'],
                                     'line':e.get('lineno'),
                                     'file':symbol_map[a]['file'],
                                     'call_id':evidence.get('call_id')})
    profile=_project_profile(count, [])
    total=sum(1 for n in nodes if n.get('type') in {'class','function','method'})
    return {'schema_version':1, 'profile':profile, 'layers':LAYERS,
            'groups':groups,'symbols':symbol_map,
            'edges':sorted(edge_map.values(),key=lambda x:(-x['count'],x['source_group'],x['target_group'])),
            'metrics':{'recognized_symbols':len(symbol_map),'classified_symbols':len(membership),
                       'unclassified_symbols':len(uncertain),'graph_symbols':total,
                       'parseable_files':len(file_results), 'unclassified_ids':uncertain[:30]},
            'limitations':['후보 역할은 검증된 기능 의미가 아님',
                           '호출 화살표는 정적 호출 후보이며 실행 순서·데이터 이동을 뜻하지 않음',
                           '이름 기반 역할은 코드 근거와 구분하여 표시함']}

/* KnitCode B mode: project-grounded architecture map with no external services. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const CALL_TYPES = new Set(['calls', 'instantiates', 'calls_override', 'calls_implicit']);
  const ROOT_CHUNK = 8;
  // Architecture layer heuristic adapted from Understand Anything (MIT):
  // packages/core/src/analyzer/layer-detector.ts. These are name-based suggestions,
  // not code-behavior assertions. See THIRD_PARTY_NOTICES.md.
  const ARCH_LAYERS = [
    {id:'entry', name:'Entry · 실행 진입', description:'__main__ 실행 블록 등 코드에서 확인한 시작점 후보', words:['__main__','wsgi','asgi','manage']},
    {id:'api', name:'Server API · 요청 수신', description:'서버 라우트·컨트롤러 등 요청을 받는 코드 후보', words:['routes','route','controller','handler','endpoint']},
    {id:'public_api', name:'Public API · 공개 인터페이스', description:'라이브러리가 외부에 제공하는 코드 인터페이스 (HTTP 서버와 구분)', words:['api','interface']},
    {id:'service', name:'Service · 기능 처리', description:'서비스·유스케이스 등 핵심 동작 관련 후보 (코드·경로 근거 확인)', words:['service','usecase','business']},
    {id:'processing', name:'Implementation · 내부 처리', description:'호출 관계상 인터페이스와 다른 계층 사이에 있는 내부 함수 집합 후보', words:[]},
    {id:'data', name:'Persistence · DB 접근', description:'데이터베이스·ORM·영속 저장 코드 후보', words:['database','db','migration','repository','repo','storage']},
    {id:'domain', name:'Domain · 데이터 모델', description:'자료형·스키마·DTO 등 (DB 저장 기능과 구분)', words:['model','models','entity','schema','dto']},
    {id:'ui', name:'UI · 화면', description:'화면·뷰·컴포넌트 관련 이름', words:['component','view','page','screen','layout','widget','ui','frontend']},
    {id:'middleware', name:'Middleware · 요청 보조', description:'미들웨어·인터셉터·가드 관련 이름', words:['middleware','interceptor','guard','filter','pipe']},
    {id:'external', name:'External · 외부 통신', description:'HTTP 클라이언트·외부 SDK·전송 어댑터 관련 코드 후보', words:['client','integration','external','sdk','vendor','adapter','transport']},
    {id:'background', name:'Background · 비동기 작업', description:'작업자·스케줄러·큐·프로세서 관련 이름', words:['worker','job','queue','cron','consumer','processor','scheduler','background']},
    {id:'utils', name:'Utilities · 공통 기능', description:'공통 유틸리티·헬퍼·공유 코드 관련 이름', words:['util','helper','lib','common','shared']},
    {id:'tests', name:'Test · 검증', description:'테스트 파일·테스트 관련 디렉터리', words:['test','spec','__test__','__tests__','testing','fixtures']},
    {id:'config', name:'Config · 설정', description:'환경 설정·구성 파일 관련 이름', words:['config','setting','env']},
  ];
  const CORE_LAYER = {id:'core', name:'미분류 · 역할 확인 필요', description:'확실한 역할 단서가 부족한 코드. Core 기능으로 단정하지 않습니다.', words:[]};
  let viewStyle = 'roles';
  // Exact path segment matching first, filename tokens second. No substring guesses.
  function detectArchitectureLayer(filePath, evidence) {
    // Code evidence is produced by architecture_evidence.py using Python AST only.
    // It remains a role hypothesis; it does NOT establish verified business semantics.
    if (evidence && typeof evidence.role === 'string') {
      const found = ARCH_LAYERS.find(x=>x.id===evidence.role) || (evidence.role==='core' ? CORE_LAYER : undefined);
      if (found) return {layer:found,evidence:(evidence.evidence||[])[0] || '근거 없음',
        basis:evidence.basis || 'none',confidence:evidence.confidence || 'low'};
    }
    const parts = String(filePath).replace(/\\/g,'/').toLowerCase().split('/');
    const fileName = parts.pop() || '';
    if (isTestPath(filePath)) return {layer:ARCH_LAYERS.find(x=>x.id==='tests'), evidence:'테스트 경로 또는 파일명'};
    for (const layer of ARCH_LAYERS) {
      for (const dir of parts) {
        if (layer.words.some(w=>dir===w || dir===w+'s')) return {layer,evidence:dir+'/'};
      }
    }
    const tokens = fileName.replace(/\.py$/,'').split(/[_\-.]+/).filter(Boolean);
    for (const layer of ARCH_LAYERS) {
      const word = tokens.find(t=>layer.words.some(w=>t===w||t===w+'s'));
      if (word) return {layer,evidence:word+' (파일명)'};
    }
    return {layer:CORE_LAYER,evidence:'일치하는 경로 규칙 없음'};
  }
  const SVG_NS = 'http://www.w3.org/2000/svg';
  let source, model;
  let showTests = false, selectedGroup, selectedFile, selectedFunction;
  let activeQuestion = '', highlight = new Set();
  let resizeQueued = false;

  function element(tag, text, parent, className, onClick) {
    const n = document.createElement(tag);
    if (text !== undefined && text !== null) n.textContent = String(text);
    if (className) n.className = className;
    if (parent) parent.appendChild(n);
    if (onClick) n.addEventListener('click', onClick);
    return n;
  }
  function isTestPath(p) { return /(^|\/)(test|tests|testing|fixtures)(\/|$)|(^|\/)test_[^/]+\.py$|_test\.py$/.test(p); }
  function displayName(file) { return file.split('/').pop(); }
  function truncate(s, max = 42) { return s.length > max ? s.slice(0, max - 1) + '…' : s; }
  function groupLabel(key, chunk) {
    if (key === '@root') return chunk == null ? '프로젝트 최상위' : `최상위 파일 · ${chunk + 1}`;
    return key + '/';
  }

  // Symbol-level architectural groups supplied by architecture_hierarchy.py.
  // Keep the original file/folder display for compatibility. A single file may
  // belong to many functional areas, but each symbol has one navigable group.
  function computeSemantic(data) {
    const h = data.architecture_hierarchy;
    const files = new Map(), nodeById = new Map(), nodeGroup = new Map();
    const incomingNodes = new Map(), outgoingNodes = new Map();
    for (const n of data.nodes || []) {
      nodeById.set(n.id,n);
      if (n.type === 'file' && n.file) files.set(n.file, {
        id:n.id,path:n.file,name:displayName(n.file),test:isTestPath(n.file),
        changes:data.history?.changes?.[n.file] || 0,functions:[],groups:new Set(),
        group:undefined,roleAnalysis:data.architecture_roles?.[n.file] || null
      });
    }
    for (const n of data.nodes || []) if (['function','method'].includes(n.type) && files.has(n.file)) {
      files.get(n.file).functions.push(n);
    }
    const groups = new Map();
    for (const gg of h.groups) {
      if (!gg.function_ids?.length) continue;
      const memberFiles = [...new Set(gg.files || [])].map(f=>files.get(f)).filter(Boolean);
      const g = {
        id:gg.id,name:gg.name,description:gg.description,
        layer:gg.layer,layerName:gg.layer_name,roleId:gg.role,
        evidence:new Set(gg.examples?.flatMap(e=>e.evidence?.map(v=>v.detail)||[]) || []),
        files:memberFiles, functionIds:gg.function_ids.filter(id=>nodeById.has(id)),
        test:!!gg.test,codeFiles:gg.code_evidence_count || 0,
        pathFiles:gg.name_hint_count || 0,graphFiles:0,undecidedFiles:0,
        functions:gg.symbol_count || gg.function_ids.length,
        changes:memberFiles.reduce((sum,f)=>sum+(f.changes||0),0),
        incoming:0,outgoing:0,incomingGroups:new Set(),outgoingGroups:new Set()
      };
      groups.set(g.id,g);
      for (const id of g.functionIds) nodeGroup.set(id,g.id);
      for (const f of memberFiles) {
        f.groups.add(g.id);
        if (!f.group) f.group=g.id;
      }
    }
    // An explicit uncertainty bucket is not a 'core service' claim.
    const unmatched = (h.metrics?.unclassified_ids || []).filter(id=>nodeById.has(id));
    if (unmatched.length) {
      const uf=[...new Set(unmatched.map(id=>nodeById.get(id)?.file))].map(f=>files.get(f)).filter(Boolean);
      groups.set('cap:unclassified',{
        id:'cap:unclassified',name:'분류 보류 · 확인 필요',roleId:'unclassified',layer:'unknown',
        layerName:'확인 필요',description:'이름과 AST만으로 책임을 확인하기 어려운 심볼. 핵심 기능이라고 단정하지 않습니다',
        evidence:new Set(),files:uf,functionIds:unmatched,test:uf.length>0&&uf.every(f=>f.test),
        codeFiles:0,pathFiles:0,graphFiles:0,undecidedFiles:unmatched.length,functions:h.metrics?.unclassified_symbols||unmatched.length,
        changes:0,incoming:0,outgoing:0,outgoingGroups:new Set(),incomingGroups:new Set()
      });
      for (const id of unmatched) nodeGroup.set(id,'cap:unclassified');
    }
    const edgeMap = new Map();
    const seenCallSites = new Set();
    for (const link of h.edges || []) {
      const a=link.source_group,b=link.target_group;
      if (!groups.has(a)||!groups.has(b)||a===b) continue;
      const evs=[];
      for (const ev of link.evidence || []) {
        evs.push({source:ev.source,target:ev.target,
          sourceName:nodeById.get(ev.source)?.name || ev.source,
          targetName:nodeById.get(ev.target)?.name || ev.target,
          sourceFile:nodeById.get(ev.source)?.file || ev.file,
          targetFile:nodeById.get(ev.target)?.file || '',type:ev.type,line:ev.line});
      }
      const e={a,b,count:link.count,implicit:link.implicit||0,evidence:evs};
      edgeMap.set(a+'\0'+b,e);
      groups.get(a).outgoing += e.count;groups.get(b).incoming += e.count;
      groups.get(a).outgoingGroups.add(b);groups.get(b).incomingGroups.add(a);
    }
    for (const e of data.edges || []) if (CALL_TYPES.has(e.type)) {
      outgoingNodes.set(e.source,(outgoingNodes.get(e.source)||0)+1);
      incomingNodes.set(e.target,(incomingNodes.get(e.target)||0)+1);
    }
    const entryIds=new Set();
    for (const item of data.entry_points || []) {
      const id=typeof item==='string'?item:item?.id || item?.node_id || item?.function_id;
      if (nodeById.has(id))entryIds.add(id);
    }
    for (const id of entryIds) {
      const g=groups.get(nodeGroup.get(id));if(g)g.entry=(g.entry||0)+1;
    }
    const layerRank={interface:0,core:1,integration:2,state:3,output:4,support:5,unknown:6};
    const sorted=[...groups.values()].sort((a,b)=>(layerRank[a.layer]??8)-(layerRank[b.layer]??8)||b.functions-a.functions||a.name.localeCompare(b.name));
    // The model is an architectural hypothesis, not a topological execution plan.
    return {files,groups,sorted,edges:[...edgeMap.values()],nodeById,nodeGroup,
      entryIds,incomingNodes,outgoingNodes,semantic:true,profile:h.profile,
      metrics:h.metrics || {}};
  }

  function compute(data) {
    if (viewStyle === 'roles' && data.architecture_hierarchy?.groups?.length) return computeSemantic(data);
    const files = new Map();
    const nodeFile = new Map();
    const nodeById = new Map();
    for (const n of data.nodes || []) {
      nodeById.set(n.id, n);
      if (n.file) nodeFile.set(n.id, n.file);
      if (n.type === 'file' && n.file) files.set(n.file, {
        id: n.id, path: n.file, name: displayName(n.file),
        test: isTestPath(n.file), changes: data.history?.changes?.[n.file] || 0,
        functions: [], group: undefined, roleAnalysis: data.architecture_roles?.[n.file] || null
      });
    }
    for (const n of data.nodes || []) if (['function', 'method'].includes(n.type) && files.has(n.file)) {
      files.get(n.file).functions.push(n);
    }
    const roots = [...files.values()].filter(f => !f.path.includes('/')).sort((a,b) => a.path.localeCompare(b.path));
    const rootChunkByFile = new Map();
    roots.forEach((f, i) => rootChunkByFile.set(f.path, roots.length <= ROOT_CHUNK ? null : Math.floor(i / ROOT_CHUNK)));
    const groups = new Map();
    const coreOrdered = viewStyle === 'roles' ? [...files.values()]
      .filter(f=>detectArchitectureLayer(f.path, f.roleAnalysis).layer.id==='core')
      .sort((a,b)=>a.path.localeCompare(b.path)) : [];
    const coreChunk = new Map(coreOrdered.map((f,i)=>[f.path,coreOrdered.length<=ROOT_CHUNK?null:Math.floor(i/ROOT_CHUNK)]));
    for (const f of files.values()) {
      const role = detectArchitectureLayer(f.path, f.roleAnalysis);
      const first = viewStyle === 'roles' ? 'role:'+role.layer.id : (f.path.includes('/') ? f.path.split('/')[0] : '@root');
      const coreFiles = viewStyle === 'roles' && role.layer.id === 'core';
      // Keep large unclassified groups readable; unlike semantics, these splits
      // are purely presentational and must never imply architectural layers.
      const coreIndex = coreFiles ? coreChunk.get(f.path) : null;
      const chunk = coreFiles ? coreIndex : (viewStyle === 'folders' && first === '@root' ? rootChunkByFile.get(f.path) : null);
      const id = chunk == null ? first : `${first}:${chunk}`;
      let g = groups.get(id);
      if (!g) {
        g = {id, name: viewStyle === 'roles' ? (role.layer.name + (chunk != null ? ` · ${chunk+1}` : '')) : groupLabel(first, chunk),
          description: viewStyle === 'roles' ? role.layer.description : '실제 파일 경로에서 묶은 디렉터리 단위',
          roleId: viewStyle === 'roles' ? role.layer.id : 'folder', evidence: new Set(), files: [], test: true,
          codeFiles: 0, pathFiles: 0, graphFiles: 0, undecidedFiles: 0,
          functions: 0, changes: 0, incoming: 0, outgoing: 0, outgoingGroups: new Set(), incomingGroups: new Set()};
        groups.set(id, g);
      }
      f.group = id;
      g.evidence.add(viewStyle === 'roles' ? role.evidence : f.path.split('/')[0] || f.path);
      g.files.push(f);
      if (role.basis === 'code') g.codeFiles++;
      else if (role.basis === 'callgraph') g.graphFiles++;
      else if (role.basis === 'path') g.pathFiles++;
      else g.undecidedFiles++;
      g.functions += f.functions.length;
      g.changes += Number(f.changes) || 0;
      if (!f.test) g.test = false;
    }
    for (const g of groups.values()) g.files.sort((a,b) => a.path.localeCompare(b.path));

    const edges = new Map();
    const seenPairs = new Set();
    const incomingNodes = new Map(), outgoingNodes = new Map();
    for (const e of data.edges || []) {
      if (!CALL_TYPES.has(e.type)) continue;
      const fromFile = files.get(nodeFile.get(e.source));
      const toFile = files.get(nodeFile.get(e.target));
      if (!fromFile || !toFile) continue;
      const nodeKey = e.source + '\u0000' + e.target + '\u0000' + e.type;
      if (seenPairs.has(nodeKey)) continue;
      seenPairs.add(nodeKey);
      outgoingNodes.set(e.source, (outgoingNodes.get(e.source) || 0) + 1);
      incomingNodes.set(e.target, (incomingNodes.get(e.target) || 0) + 1);
      if (fromFile.group === toFile.group) continue;
      const key = fromFile.group + '\u0000' + toFile.group;
      if (!edges.has(key)) edges.set(key, {a: fromFile.group, b: toFile.group, count: 0, implicit: 0, evidence: []});
      const link = edges.get(key);
      link.count++;
      if (link.evidence.length < 12) {
        const src = nodeById.get(e.source), dst = nodeById.get(e.target);
        link.evidence.push({source:e.source, target:e.target, sourceName:src?.name || e.source,
          targetName:dst?.name || e.target, sourceFile:fromFile.path, targetFile:toFile.path, type:e.type});
      }
      if (e.type === 'calls_implicit') link.implicit++;
      const a = groups.get(fromFile.group), b = groups.get(toFile.group);
      a.outgoing++; b.incoming++;
      a.outgoingGroups.add(b.id); b.incomingGroups.add(a.id);
    }
    const entryIds = new Set();
    for (const item of data.entry_points || []) {
      const id = typeof item === 'string' ? item : item?.id || item?.node_id || item?.function_id;
      if (nodeById.has(id)) entryIds.add(id);
    }
    for (const f of files.values()) {
      for (const n of f.functions) if (entryIds.has(n.id)) {
        groups.get(f.group).entry = (groups.get(f.group).entry || 0) + 1;
      }
    }
    // Stable ordering. Entry candidates first, then groups with more outgoing than incoming edges.
    const sorted = [...groups.values()].sort((a,b) => {
      const score = g => (g.entry || 0) * 50 + (g.outgoing > 0 && g.incoming === 0 ? 20 : 0) + Math.min(g.outgoing, 10);
      if (viewStyle === 'roles') {
        const rank = id => ARCH_LAYERS.findIndex(x=>x.id === id);
        const ra = rank(a.roleId), rb = rank(b.roleId);
        if (ra !== rb) return (ra === -1 ? 99 : ra) - (rb === -1 ? 99 : rb);
      }
      return score(b) - score(a) || a.name.localeCompare(b.name);
    });
    return {files, groups, sorted, edges: [...edges.values()], nodeById, entryIds, incomingNodes, outgoingNodes};
  }
  function availableGroups() { return model?.sorted.filter(g => showTests || !g.test) || []; }
  function visibleEdges() {
    const shown = new Set(availableGroups().map(g => g.id));
    return model.edges.filter(e => shown.has(e.a) && shown.has(e.b)).sort((a,b) => b.count - a.count);
  }
  function summary() {
    if (!model) return;
    const groups = availableGroups();
    const project = source.project || {};
    $('b-overview').textContent = model.semantic ? `${model.profile?.label || 'Python 프로젝트'} · 함수·클래스 단위 기능 후보 ${model.metrics?.classified_symbols || 0}개 / 분류 보류 ${model.metrics?.unclassified_symbols || 0}개 · 그룹 간 정적 호출 근거를 표시합니다.` : project.description
      ? `${project.name || '프로젝트'} — ${truncate(String(project.description), 190)}`
      : `${project.name || 'Python 프로젝트'}의 파일·함수 호출 관계를 ${viewStyle === 'roles' ? '코드 사용 신호와 경로 규칙에 따른 역할 후보' : '실제 폴더'}로 묶어 표시합니다. 기능적 의미나 실행 순서는 확정되지 않습니다.`;
    $('b-stat-files').textContent = String([...model.files.values()].filter(f => showTests || !f.test).length);
    $('b-stat-groups').textContent = String(groups.length);
    $('b-stat-links').textContent = String(visibleEdges().length);
    $('b-legend').textContent = model.semantic ? '그룹은 함수·클래스별 역할 가설이며 AST 동작 근거와 함수 이름 단서를 구분합니다 · 화살표는 원본 정적 호출 후보만 집계 · 실행 순서나 데이터 흐름을 의미하지 않습니다' : `${viewStyle === 'roles' ? '역할 이름은 Python AST 코드 신호와 경로 규칙을 종합한 추정 · 근거는 파일 선택 시 확인 · ' : '실제 디렉터리 기준 · '}정적 호출 관계 ${visibleEdges().length}개 방향 집계 · 선은 최대 18개 · 실행 순서·데이터 흐름을 의미하지 않음`;
  }
  function selectGroup(id) {
    if (!model?.groups.has(id)) return;
    selectedGroup = id; selectedFile = undefined; selectedFunction = undefined;
    activeQuestion = ''; highlight = new Set([id]);
    for(const link of model.edges)if(link.a===id)highlight.add(link.b);else if(link.b===id)highlight.add(link.a);
    render();
  }
  function selectFile(path) {
    const f = model?.files.get(path); if (!f) return;
    selectedGroup = f.groups?.has(selectedGroup) ? selectedGroup : f.group; selectedFile = path; selectedFunction = undefined;
    activeQuestion = ''; highlight = new Set([f.group]);
    render();
  }
  function selectFunction(id) {
    const n = model?.nodeById.get(id); if (!n || !model.files.has(n.file)) return;
    selectedGroup = model.nodeGroup?.get(id) || model.files.get(n.file).group; selectedFile = n.file; selectedFunction = id;
    activeQuestion = ''; highlight = new Set([selectedGroup]);
    render();
  }
  function renderGraph() {
    const box = $('b-group-grid'); box.replaceChildren();
    const groups = availableGroups();
    if (!groups.length) { element('p', '분석 결과에서 표시할 Python 파일을 찾지 못했습니다.', box, 'b-placeholder'); return; }
    // Place components by graph depth, so the arrows mostly follow a left-to-right story.
    // The heuristic falls back to a single column for cyclic/isolated groups; no execution order is claimed.
    const ids = new Set(groups.map(g => g.id));
    const uniqueEdges = visibleEdges();
    const inDegree = new Map(groups.map(g => [g.id, 0]));
    const forward = new Map(groups.map(g => [g.id, []]));
    const level = new Map(groups.map(g => [g.id, 0]));
    for (const edge of uniqueEdges) {
      if (!ids.has(edge.a) || !ids.has(edge.b)) continue;
      if (forward.get(edge.a).includes(edge.b)) continue;
      forward.get(edge.a).push(edge.b);
      inDegree.set(edge.b, inDegree.get(edge.b) + 1);
    }
    const queue = groups.filter(g => inDegree.get(g.id) === 0).map(g => g.id);
    for (let i = 0; i < queue.length; i++) {
      const id = queue[i];
      for (const next of forward.get(id)) {
        level.set(next, Math.max(level.get(next), Math.min(4, level.get(id) + 1)));
        inDegree.set(next, inDegree.get(next) - 1);
        if (inDegree.get(next) === 0) queue.push(next);
      }
    }
    // In the logical-layer view, stable categorical lanes provide an immediate
    // architecture overview even when the call graph has cycles. Lane order is
    // for readability; actual call direction is always carried by the arrows.
    if (viewStyle === 'roles') {
      const lanes = model.semantic ? {interface:0,core:1,integration:2,state:3,output:3,support:2,unknown:3} : {entry:0,api:0,public_api:0,middleware:0,ui:0,
        service:1,processing:1,background:1,external:1,domain:1,
        data:2,utils:2,config:2,core:3,tests:3};
      for (const g of groups) level.set(g.id,lanes[model.semantic?g.layer:g.roleId]??3);
    } else if (queue.length < groups.length) {
      // Unresolved SCCs have no topological depth; spread them visually.
      const unresolved=groups.filter(g=>!queue.includes(g.id));
      unresolved.forEach((g,i)=>level.set(g.id,i%3));
    }
    const maxLevel = Math.max(...[...level.values()], 0);
    // Use one clear column per dependency depth. Large graphs can scroll horizontally.
    const cols = [];
    for (let i = 0; i <= maxLevel; i++) {
      const col=element('div', undefined, box, 'b-column');
      if(model.semantic){const titles=['진입·인터페이스','핵심 기능','연동·지원','데이터·표현·기타'];element('div',titles[i] || '관련 기능',col,'b-lane-title');}
      cols.push(col);
    }
    for (const g of groups) {
      const parent = cols[level.get(g.id) || 0];
      const active = selectedGroup === g.id;
      const dim = highlight.size && !highlight.has(g.id);
      const card = element('article', undefined, parent, 'b-group' + (active ? ' is-selected' : '') + (dim ? ' is-dim' : ''));
      card.dataset.groupId = g.id;
      const head = element('button', undefined, card, 'b-group-title', () => selectGroup(g.id));
      element('span', g.name, head, 'b-group-name');
      card.dataset.role = g.roleId;
      if (model.semantic) card.dataset.layer = g.layer;
      card.title = g.description;
      element('p', g.description, card, 'b-group-description');
      if (viewStyle === 'roles') element('small', model.semantic ? `${g.layerName} · AST 증거 ${g.codeFiles} · 이름 후보 ${g.pathFiles}` : `코드 근거 ${g.codeFiles} · 경로 추정 ${g.pathFiles} · 미분류 ${g.undecidedFiles}`, card, 'b-source-badge');
      element('span', '↗', head, 'b-group-enter');
      element('p', model.semantic ? `${g.functions}개 심볼 · ${g.files.length}개 파일` : `${g.files.length}개 파일 · ${g.functions}개 함수`, card, 'b-group-meta');
      const chips = element('div', undefined, card, 'b-files');
      if (model.semantic) {
        for(const id of (g.functionIds || []).slice(0,4)) {
          const fn=model.nodeById.get(id);if(!fn)continue;
          const chip=element('button',truncate(fn.name.split('.').slice(-2).join('.'),27),chips,'b-file-chip',()=>selectFunction(id));
          chip.title=`${fn.file}:${fn.lineno||1}`;
        }
        if(g.functions>4)element('button',`+ ${g.functions-4}개 심볼`,chips,'b-file-chip b-more-chip',()=>selectGroup(g.id));
      } else {
        for (const f of g.files.slice(0, 5)) {
          const b = element('button', truncate(f.name, 24), chips, 'b-file-chip' + (f.path === selectedFile ? ' active' : ''), () => selectFile(f.path));
          b.title = f.path;
        }
        if (g.files.length > 5) element('button', `+ ${g.files.length - 5}개 파일`, chips, 'b-file-chip b-more-chip', () => selectGroup(g.id));
      }
      const bottom = element('div', undefined, card, 'b-group-bottom');
      element('span', `↗ 타 영역 호출 ${g.outgoing}개`, bottom);
      if (g.changes) element('span', `Git 변경 ${g.changes}회`, bottom);
    }
    scheduleLinks();
  }
  function svg(tag, attrs, parent, txt) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [k,v] of Object.entries(attrs || {})) node.setAttribute(k,String(v));
    if (txt != null) node.textContent=String(txt);
    if (parent) parent.appendChild(node);
    return node;
  }
  function scheduleLinks() {
    if (resizeQueued) return;
    resizeQueued = true;
    requestAnimationFrame(() => { resizeQueued = false; drawLinks(); });
  }
  function drawLinks() {
    const canvas = $('b-canvas'), layer = $('b-links');
    if (canvas.hidden || !model || $('b-mode').hidden) return;
    layer.replaceChildren();
    const W = Math.max(canvas.scrollWidth, canvas.clientWidth), H = Math.max(canvas.scrollHeight, canvas.clientHeight);
    layer.setAttribute('viewBox', `0 0 ${W} ${H}`);
    layer.setAttribute('width', W); layer.setAttribute('height', H);
    const defs = svg('defs', {}, layer);
    const marker = svg('marker', {id:'b-arrow', viewBox:'0 0 10 10', refX:'9', refY:'5', markerWidth:'5', markerHeight:'5', orient:'auto-start-reverse'}, defs);
    svg('path', {d:'M 0 0 L 10 5 L 0 10 z', fill:'var(--b-edge)'}, marker);
    const origin = canvas.getBoundingClientRect();
    const rects = new Map();
    for (const node of $('b-group-grid').querySelectorAll('.b-group')) {
      const r = node.getBoundingClientRect();
      rects.set(node.dataset.groupId, {left:r.left-origin.left, right:r.right-origin.left, top:r.top-origin.top, bottom:r.bottom-origin.top,
        cx:(r.left+r.right)/2-origin.left, cy:(r.top+r.bottom)/2-origin.top});
    }
    const edges = visibleEdges().slice(0, model.semantic ? 14 : 18);
    const edgeDirections = new Set(edges.map(e=>e.a+'\u0000'+e.b));
    for (const e of edges) {
      const a = rects.get(e.a), b = rects.get(e.b); if (!a || !b) continue;
      const dx = b.cx-a.cx, dy=b.cy-a.cy;
      const horizontal = Math.abs(dx) > Math.abs(dy) * .9;
      let x1,y1,x2,y2, curve;
      if (horizontal) {
        const right = dx > 0;
        x1=right?a.right:a.left; x2=right?b.left:b.right; y1=a.cy; y2=b.cy;
        // Opposite-direction calls must not cover one another.
        if (edgeDirections.has(e.b+'\u0000'+e.a)) {
          const offset = e.a < e.b ? -9 : 9;
          y1+=offset;y2+=offset;
        }
        const spread = Math.max(24,Math.min(65,Math.abs(x2-x1)*.4));
        curve=`M ${x1} ${y1} C ${x1+(right?spread:-spread)} ${y1}, ${x2-(right?spread:-spread)} ${y2}, ${x2} ${y2}`;
      } else {
        const down = dy > 0;
        x1=a.cx; x2=b.cx; y1=down?a.bottom:a.top; y2=down?b.top:b.bottom;
        const spread=Math.max(24,Math.min(60,Math.abs(y2-y1)*.35));
        curve=`M ${x1} ${y1} C ${x1} ${y1+(down?spread:-spread)}, ${x2} ${y2-(down?spread:-spread)}, ${x2} ${y2}`;
      }
      const emphasized = !highlight.size || highlight.has(e.a) || highlight.has(e.b);
      const p = svg('path', {d:curve, class:'b-link' + (emphasized?'':' b-link-dim'), 'marker-end':'url(#b-arrow)'}, layer);
      svg('title', {}, p, `${model.groups.get(e.a)?.name} → ${model.groups.get(e.b)?.name}: 정적 함수 연결 ${e.count}개 (선 선택 시 관련 호출 근거)`);
      p.style.pointerEvents='stroke';
      p.style.cursor='pointer';
      p.addEventListener('click', () => showEdgeEvidence(e));
    }
  }

  function showEdgeEvidence(link) {
    const answer = $('b-question-answer'); answer.replaceChildren();
    $('b-answer-heading').textContent = '영역 간 호출 근거';
    const from = model.groups.get(link.a), to = model.groups.get(link.b);
    element('strong', `${from?.name || link.a} → ${to?.name || link.b}`, answer);
    element('p', `정적 호출 후보 ${link.count}개를 합산한 연결선입니다. 실제 실행 순서·빈도는 알 수 없습니다.`, answer);
    const rows = element('div', undefined, answer, 'b-edge-examples');
    for (const ev of link.evidence.slice(0, 6)) {
      const item = element('div', undefined, rows, 'b-edge-example');
      element('button', `${truncate(ev.sourceName,20)}() → ${truncate(ev.targetName,20)}()`, item, 'b-edge-example-title', () => selectFunction(ev.source));
      element('small', `${ev.sourceFile} → ${ev.targetFile}`, item);
    }
    highlight = new Set([link.a,link.b]); selectedGroup = link.a;
    selectedFile=undefined;selectedFunction=undefined;activeQuestion='';
    renderGraph();detail();
  }
  function setActions() {
    $('b-open-a').disabled = !selectedFunction;
    $('b-open-code').disabled = !selectedFunction;
  }
  function detail() {
    const body = $('b-detail-content'); body.replaceChildren();
    const title = $('b-selection-title'), subtitle = $('b-selection-subtitle');
    if (!model) {
      title.textContent = '분석을 준비하고 있습니다'; subtitle.textContent = '';
      element('p', '분석을 시작하면 프로젝트 구조가 표시됩니다.', body, 'b-placeholder'); setActions(); return;
    }
    const group = model.groups.get(selectedGroup);
    if (!group) {
      title.textContent = '지도에서 영역 선택'; subtitle.textContent = '구성 요소를 선택하면 하위 파일·함수가 나타납니다.';
      element('p', '왼쪽 위 지도의 큰 상자를 선택하세요.', body, 'b-placeholder'); setActions(); return;
    }
    if (selectedFunction) {
      const f = model.nodeById.get(selectedFunction);
      if (!f) { selectedFunction = undefined; detail(); return; }
      title.textContent = f.name;
      subtitle.textContent = `${f.file}:${f.lineno || 1} · ${f.type} · 정적 코드 관계`;
      const expl = element('div', undefined, body, 'b-detail-summary');
      element('strong', '함수 관계 근거', expl);
      element('p', `분석된 다른 함수로 향하는 호출 후보 ${model.outgoingNodes.get(f.id) || 0}개, 이 함수를 대상으로 하는 호출 후보 ${model.incomingNodes.get(f.id) || 0}개. 실제 실행 여부는 별도 검증이 필요합니다.`, expl);
      const sym=source.architecture_hierarchy?.symbols?.[f.id];
      if(sym) {element('p',`기능 후보: ${sym.label} · 판별 근거: ${sym.basis==='ast'?'AST 사용 근거':sym.basis==='mixed'?'함수 구문·명칭':sym.basis==='name'?'함수 이름': '판단 보류'}`,expl);
        for(const ev of (sym.evidence||[]).slice(0,4))element('p',`${ev.line}행 · ${ev.detail}`,expl);
        if(sym.facets?.length)element('p',`보조 기술 동작: ${sym.facets.join(', ')} (주된 기능과 구분)`,expl);
      }
      element('button', '← 포함된 파일 보기', body, 'b-back-detail', () => selectFile(f.file));
      setActions(); return;
    }
    if (selectedFile) {
      const file = model.files.get(selectedFile);
      if (!file) { selectedFile = undefined; detail(); return; }
      title.textContent = file.path;
      subtitle.textContent = `${group.name} · 파일의 전체 함수 ${file.functions.length}개${model.semantic ? ' (현재 그룹 소속 함수만 아래 표시)' : ''}`;
      if (viewStyle === 'roles') {
        const hint = file.roleAnalysis;
        const exp = element('div', undefined, body, 'b-detail-summary');
        const sourceLabel = hint?.basis === 'code' ? 'AST 코드 신호' : (hint?.basis === 'callgraph' ? '호출 그래프 맥락' : hint?.basis === 'path' ? '경로 이름 규칙' : '근거 부족');
        element('strong', `역할 추정 · ${sourceLabel} · 신뢰도 ${hint?.confidence === 'high' ? '높음(구문)' : hint?.confidence === 'medium' ? '중간' : '낮음'}`, exp);
        for (const item of (hint?.evidence || ['분류에 활용된 근거가 없습니다.']).slice(0,6)) element('p', item, exp);
        if (hint?.alternatives?.length) {
          element('strong', '다른 역할 후보', exp);
          for (const alt of hint.alternatives.slice(0, 3)) element('p', `${alt.label || alt.role}: 점수 ${alt.score}`, exp);
        }
        const ctx = hint?.call_context;
        if (ctx && (ctx.inbound_files || ctx.outbound_files)) {
          element('strong', '기존 A 그래프의 파일 간 호출 근거', exp);
          element('p', `이 파일을 호출하는 다른 파일 ${ctx.inbound_files}개 · 이 파일에서 호출하는 다른 파일 ${ctx.outbound_files}개`, exp);
          const callRows = element('div', undefined, exp, 'b-related');
          for (const ex of (ctx.examples || []).slice(0, 4)) {
            element('button', `${ex.direction === 'outgoing' ? '→':'←'} ${ex.from} → ${ex.to}`, callRows, 'b-related-link', () => {
              if (ex.source_id) window.KnitBBridge?.openA(ex.source_id);
            });
          }
        }
        element('small', '이 분류는 코드 구문을 기반으로 한 후보이며 실제 동작을 증명하지 않습니다.', exp);
      }
      const list = element('div', undefined, body, 'b-detail-list');
      element('button', `← ${group.name} 전체 파일`, list, 'b-back-detail', () => selectGroup(group.id));
      if (!file.functions.length) element('p', '분석된 함수 정의가 없습니다.', list, 'b-placeholder');
      const relatedFunctions = model.semantic ? file.functions.filter(n=>model.nodeGroup.get(n.id)===group.id) : file.functions;
      for (const fn of [...relatedFunctions].sort((a,b)=>(a.lineno || 0)-(b.lineno || 0)).slice(0, 80)) {
        const item = element('div', undefined, list, 'b-item');
        element('button', `${fn.name}()`, item, 'b-item-main', () => selectFunction(fn.id));
        element('small', `${fn.lineno || 1}행 · 호출 대상 ${model.outgoingNodes.get(fn.id)||0}개`, item);
        element('button', '코드 ↗', item, 'b-inline-action', () => window.KnitBBridge?.openCode(fn.id));
      }
      if (file.functions.length > 80) element('p', `최대 80개 함수를 표시합니다. 나머지 ${file.functions.length-80}개는 A 모드에서 탐색하세요.`, body, 'b-placeholder');
      setActions(); return;
    }
    title.textContent = group.name;
    subtitle.textContent = `파일 ${group.files.length}개 · 함수 ${group.functions}개 · 다른 영역 호출 관계 ${group.outgoingGroups.size + group.incomingGroups.size}개 방향`;
    const expl = element('div', undefined, body, 'b-detail-summary');
    element('strong', '구성 영역 요약', expl);
    element('p', model.semantic ? `${group.layerName} · ${group.functions}개 심볼이 이 기능 영역의 후보입니다. AST 직접 근거 ${group.codeFiles}개, 이름 단서 ${group.pathFiles}개. 역할은 자동 분류 결과이며 개별 심볼에서 확인할 수 있습니다.` : viewStyle === 'roles' ? `${group.description}. AST 코드 사용 근거 ${group.codeFiles}개 파일 · 경로명 추정 ${group.pathFiles}개 파일 · 미분류 ${group.undecidedFiles}개 파일. 실제 역할은 검증이 필요합니다.` : '같은 최상위 경로의 파일을 묶었습니다. 영역 이름은 실제 디렉터리에서 가져왔습니다.', expl);
    if (viewStyle === 'roles') {
      const evidenceText = [...group.evidence].filter(x=>x!=='일치하는 경로 규칙 없음').slice(0,7).join(', ');
      element('p', '분류 단서: ' + (evidenceText || '명확한 코드 근거 부족'), expl);
    }
    const related = visibleEdges().filter(e=>e.a===group.id||e.b===group.id).sort((a,b)=>b.count-a.count).slice(0,5);
    if (related.length) {
      const rel = element('div', undefined, body, 'b-related');
      element('strong','다른 구성 영역과의 실제 호출 근거',rel);
      for (const r of related) {
        const other = model.groups.get(r.a===group.id?r.b:r.a);
        element('button', `${r.a===group.id?'→':'←'} ${other?.name||'영역'} · ${r.count}개 호출 후보 보기`, rel,'b-related-link', () => showEdgeEvidence(r));
      }
    }
    const list = element('div', undefined, body, 'b-detail-list');
    if (model.semantic) {
      for (const id of (group.functionIds || []).slice(0,90)) {
        const fn=model.nodeById.get(id);if(!fn)continue;
        const item=element('div',undefined,list,'b-item');
        element('button',fn.name,item,'b-item-main',()=>selectFunction(id));
        element('small',`${fn.file}:${fn.lineno||1} · ${model.outgoingNodes.get(id)||0}개 호출 후보`,item);
        element('button','코드 ↗',item,'b-inline-action',()=>window.KnitBBridge?.openCode(id));
      }
      if(group.functionIds.length>90)element('p',`추가 ${group.functionIds.length-90}개 심볼은 A모드에서 확인할 수 있습니다.`,body,'b-placeholder');
      setActions();return;
    }
    for (const file of group.files) {
      const item = element('div', undefined, list, 'b-item');
      element('button', file.path, item, 'b-item-main', () => selectFile(file.path));
      element('small', `함수 ${file.functions.length}개 · ${file.roleAnalysis?.basis==='code'?'AST 근거':file.roleAnalysis?.basis==='callgraph'?'호출 관계 근거':file.roleAnalysis?.basis==='path'?'경로 추정':'미분류'}${file.changes?' · Git 변경 '+file.changes+'회':''}`, item);
      element('button', '펼치기', item, 'b-inline-action', () => selectFile(file.path));
    }
    setActions();
  }
  function ask(question) {
    if (!model) return;
    activeQuestion = question;
    for (const btn of document.querySelectorAll('[data-b-question]')) btn.classList.toggle('active', btn.dataset.bQuestion === question);
    const answer = $('b-question-answer'); answer.replaceChildren();
    const labels={entry:'어디서부터 읽을까?',service:'핵심 처리 영역은?',data:'데이터 저장·조회는 어디서?',external:'외부 API 연동은?',connected:'어떤 영역이 많이 연결될까?',files:'파일이 많은 영역은?',changes:'최근 변경된 영역은?'};
    $('b-answer-heading').textContent = labels[question] || '질문에 대한 답변';
    let picks = [], text='';
    const groups = availableGroups();
    if (question === 'entry') {
      const entryFiles = [...model.entryIds].map(id => model.nodeById.get(id)).filter(n => n && model.files.has(n.file));
      picks = [...new Set(entryFiles.map(n => model.files.get(n.file).group))].map(id=>model.groups.get(id)).filter(g=>groups.includes(g));
      if (picks.length) text = `분석 엔진이 기록한 진입점 후보가 ${entryFiles.length}개 있습니다. 시작 후보가 속한 영역을 표시합니다.`;
      else {
        // A name-based heuristic is never represented as a verified call entry point.
        picks = model.semantic ? groups.filter(g=>g.layer==='interface'&&['cli','setup','server','public_api'].includes(g.roleId)).slice(0,6) : groups.filter(g => g.files.some(f => /(^|\/)(__main__|main|app|cli|manage|wsgi|asgi)\.py$/i.test(f.path))).slice(0, 6);
        text = picks.length ? '확인된 진입점이 없어 일반적인 실행 파일명에 맞는 후보를 표시합니다. 실제 시작점은 확인이 필요합니다.' : '확인된 진입점이 없습니다. 코드에 따라 실행이 시작되는 위치는 다를 수 있습니다.';
      }
    } else if (question === 'data' || question === 'external' || question === 'service') {
      const roleId = question === 'data' ? 'data' : question === 'external' ? 'external' : 'service';
      const matchingRoles = roleId === 'service' ? new Set(['service','processing']) : new Set([roleId]);
      picks = model.semantic ? groups.filter(g => question==='data' ? ['database','file_io','history'].includes(g.roleId)
        : question==='external' ? ['http_client','ssh','transfer','tunnel'].includes(g.roleId)
        : g.layer==='core') : groups.filter(g => matchingRoles.has(g.roleId));
      if (!picks.length && viewStyle === 'folders') {
        picks = groups.filter(g => g.files.some(f => matchingRoles.has(f.roleAnalysis?.role)));
      }
      if (model.semantic) {
        const names=picks.map(g=>g.name).join(' / ');
        const total=picks.reduce((sum,g)=>sum+g.functions,0);
        const code=picks.reduce((sum,g)=>sum+g.codeFiles,0);
        text=picks.length ? `${question==='data'?'데이터·상태':question==='external'?'외부 연동':'핵심 기능'} 관련 후보 ${picks.length}개 영역(${total}개 심볼)입니다. ${names}. 관련 파일: ${[...new Set(picks.flatMap(g=>g.files.map(f=>f.path)))].slice(0,5).join(', ')}. 코드 단서가 확인된 심볼은 ${code}개이며 나머지는 이름에 따른 후보입니다. 연결선을 누르면 실제 정적 호출 근거를 확인할 수 있습니다.` : '해당 기능에 대한 충분한 코드 근거를 찾지 못했습니다. 실제로 기능이 없다는 뜻은 아니며 강제로 영역을 생성하지 않습니다.';
        if(question==='data' && picks.length && !picks.some(g=>g.roleId==='database')) text += ' 특히 DB 접근은 확인되지 않았고 로컬 파일·상태 관리 후보만 발견됐습니다.';
      } else text = picks.length ? '소스코드·경로 단서로 추정한 역할 영역입니다. 해당 파일을 선택하면 코드 근거를 확인할 수 있습니다.' : '현재 분류 결과에 해당 역할 후보가 없습니다. 실제 코드에서 관련 기능이 없다는 뜻은 아닙니다.';
    } else if (question === 'connected') {
      picks = groups.filter(g => g.outgoing+g.incoming>0).sort((a,b)=>(b.outgoing+b.incoming)-(a.outgoing+a.incoming)).slice(0, 4);
      text = '서로 다른 영역을 연결하는 정적 호출 후보의 수를 기준으로 표시합니다. 중요도나 실제 실행 빈도와 같지는 않습니다.';
    } else if (question === 'files') {
      picks = groups.slice().sort((a,b)=>b.files.length-a.files.length).slice(0, 4);
      text = 'Python 파일 개수가 많은 영역입니다. 폴더의 크기가 곧 실행상의 중요도를 의미하지는 않습니다.';
    } else if (question === 'changes') {
      picks = groups.filter(g=>g.changes>0).sort((a,b)=>b.changes-a.changes).slice(0, 4);
      text = picks.length ? 'Git 이력에서 파일별 변경 횟수를 합산한 결과입니다. 여러 파일이 한 커밋에서 바뀌면 각각 집계됩니다.' : '분석 결과에 집계된 Git 변경 이력이 없습니다.';
    }
    highlight = new Set(picks.map(g=>g.id));
    if (picks.length) selectedGroup = picks[0].id;
    selectedFile = undefined; selectedFunction = undefined;
    element('p', text, answer);
    if (picks.length) {
      const links = element('div', undefined, answer, 'b-answer-links');
      for (const g of picks) element('button', g.name, links, undefined, () => selectGroup(g.id));
    }
    summary(); renderGraph(); detail();
  }
  function selectionAnswer() {
    if (!model || activeQuestion) return;
    const answer = $('b-question-answer');
    const heading = $('b-answer-heading');
    answer.replaceChildren();
    const group = model.groups.get(selectedGroup);
    if (selectedFunction) {
      const fn = model.nodeById.get(selectedFunction);
      heading.textContent = '선택한 함수 요약';
      if (fn) element('p', `${fn.name}() · ${fn.file}:${fn.lineno || 1} · 호출 대상 ${model.outgoingNodes.get(fn.id) || 0}개 후보`, answer);
    } else if (selectedFile) {
      const file = model.files.get(selectedFile);
      heading.textContent = '선택한 파일 요약';
      if (file) {
        element('strong', file.path, answer);
        element('p', `${group?.name || '역할 미분류'} · 함수 ${file.functions.length}개 · 역할 근거 ${file.roleAnalysis?.basis || '없음'}`, answer);
        for (const line of (file.roleAnalysis?.evidence || []).slice(0, 3)) element('p', line, answer);
      }
    } else if (group) {
      heading.textContent = '선택한 영역 요약';
      element('strong', group.name, answer);
      element('p', model.semantic ? `${group.layerName} · ${group.functions}개 심볼 · 관련 파일 ${group.files.length}개. 코드 AST 근거 ${group.codeFiles}개와 이름 추정 ${group.pathFiles}개를 구분합니다.` : `${group.description} · 파일 ${group.files.length}개 · 함수 ${group.functions}개`, answer);
      element('p', '역할 분류는 추정이며, 호출 관계는 정적 분석 후보입니다. 아래에서 상세 코드 근거를 확인할 수 있습니다.', answer);
    } else {
      heading.textContent = '프로젝트 구조 안내';
      element('p', '오른쪽에서 질문을 선택하거나 지도 속 구성 영역을 누르세요.', answer);
    }
  }
  function render() {
    if (!model) return;
    summary(); renderGraph(); detail(); selectionAnswer();
    for (const btn of document.querySelectorAll('[data-b-question]')) btn.classList.toggle('active', btn.dataset.bQuestion === activeQuestion);
  }
  function setData(data) {
    source=data; model=compute(data);
    selectedFile=undefined; selectedFunction=undefined;
    if (!model.groups.has(selectedGroup)) selectedGroup=undefined;
    activeQuestion=''; highlight=new Set();
    for (const btn of document.querySelectorAll('[data-b-question]')) btn.classList.remove('active');
    $('b-question-answer').textContent='영역을 클릭하거나 질문을 선택하면 해당 근거를 확인할 수 있습니다.';
    const first=availableGroups()[0]; if (first && !selectedGroup) selectedGroup=first.id;
    render();
  }
  function onResize() { if (!$('b-mode').hidden && model) scheduleLinks(); }
  $('b-show-tests').addEventListener('change', e => { showTests=!!e.target.checked; highlight.clear(); render(); });
  $('b-view-style').addEventListener('change', e => {
    viewStyle = e.target.value === 'folders' ? 'folders':'roles';
    if (!source) return;
    model=compute(source); selectedGroup=undefined; selectedFile=undefined; selectedFunction=undefined;
    activeQuestion=''; highlight=new Set();
    $('b-question-answer').textContent='아키텍처 영역을 누르면 파일·함수와 호출 근거를 확인할 수 있습니다.';
    const first=availableGroups()[0];if(first)selectedGroup=first.id;
    render();
  });
  $('b-reset').addEventListener('click', () => {
    selectedGroup=undefined;selectedFile=undefined;selectedFunction=undefined;activeQuestion='';highlight.clear();
    $('b-question-answer').textContent='관심 있는 질문이나 지도 속 영역을 선택해보세요.';
    render();
  });
  document.querySelectorAll('[data-b-question]').forEach(b => b.addEventListener('click', () => ask(b.dataset.bQuestion)));
  $('b-open-a').addEventListener('click', () => { if (selectedFunction) window.KnitBBridge?.openA(selectedFunction); });
  $('b-open-code').addEventListener('click', () => { if (selectedFunction) window.KnitBBridge?.openCode(selectedFunction); });
  window.KnitB = {setData, render, onResize};
})();

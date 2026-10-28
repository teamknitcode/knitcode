/* Project content is rendered only as text. No project scripts are executed. */
const api = acquireVsCodeApi();
const $ = id => document.getElementById(id);
let data, selected, depth = 1, tab = 'cochange', trail = [];
let gitValidation;
let index = new Map(), calls = [];
const IMPLICIT = {callback: '조건부 콜백 후보', property_get: 'property 읽기 후보', property_set: 'property 쓰기 후보',
  property_delete: 'property 삭제 후보'};
function el(tag, text, parent, action) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (parent) parent.append(node);
  if (action) node.addEventListener('click', action);
  return node;
}
function open(node, line) { api.postMessage({type:'open', id:node.id, line}); }
function choose(id, remember = true) {
  if (!index.has(id)) return;
  if (remember && selected && selected !== id) trail.push(selected);
  selected = id;
  render();
}
// Breadth-first distances on each directed side; cycles never expand indefinitely.
function layers(id, incoming, limit) {
  const seen = new Set([id]), result = [];
  let frontier = [id];
  for (let step = 0; step < limit; step++) {
    const next = new Set();
    for (const edge of calls) {
      const from = incoming ? edge.target : edge.source;
      const to = incoming ? edge.source : edge.target;
      if (frontier.includes(from) && !seen.has(to) && index.has(to)) next.add(to);
    }
    const ids = [...next].sort();
    ids.forEach(n => seen.add(n));
    result.push(ids);
    frontier = ids;
  }
  return result;
}
function tree() {
  $('tree').replaceChildren();
  const query = $('search').value.toLowerCase();
  for (const file of data.nodes.filter(n => n.type === 'file')) {
    const children = data.nodes.filter(n => n.file === file.file && n.type !== 'file');
    const matches = n => `${n.name} ${n.file}`.toLowerCase().includes(query);
    if (!matches(file) && !children.some(matches)) continue;
    const group = el('details', undefined, $('tree'));
    group.open = !!query || index.get(selected)?.file === file.file;
    el('summary', file.file, group);
    el('button', '파일 변경 맥락', group, () => choose(file.id)).className = 'file-link';
    for (const node of children.filter(matches)) {
      const button = el('button', node.name, group, () => choose(node.id));
      button.className = 'symbol' + (node.id === selected ? ' active' : '');
    }
  }
}
function card(id, parent, center = false) {
  const node = index.get(id);
  const box = el('article', undefined, parent); box.className = 'card' + (center ? ' center' : ''); box.dataset.nodeId = id;
  el('small', node.type.toUpperCase(), box);
  el('button', node.class_name ? `${node.class_name}.${node.name}` : node.name, box, () => choose(id)).className = 'node-name';
  el('p', `${node.file}:${node.lineno || 1}`, box);
  const actions = el('div', undefined, box); actions.className = 'actions';
  el('button', '코드 ↗', actions, () => open(node));
  if (!center) el('button', '중심으로', actions, () => choose(id));
}
function flow() {
  const box = $('flow'); box.replaceChildren();
  const node = index.get(selected);
  if (node.type === 'file') {
    el('h2', '이 파일의 함수에서 시작하세요', box);
    const list = el('div', undefined, box); list.className = 'file-symbols';
    const members = data.nodes.filter(n => n.file === node.file && n.type !== 'file');
    members.forEach(n => card(n.id, list));
    if (!members.length) el('p', '이 파일에는 분석된 함수·클래스가 없습니다.', box);
    return;
  }
  const incoming = layers(selected, true, depth), outgoing = layers(selected, false, depth);
  const lanes = el('div', undefined, box); lanes.className = 'lanes';
  function lane(ids, title, center = false) {
    const col = el('section', undefined, lanes); col.className = 'lane';
    el('h3', title, col);
    if (!ids.length) el('p', '확인된 내부 호출 없음', col).className = 'empty';
    ids.slice(0, 20).forEach(id => card(id, col, center));
    if (ids.length > 20) {
      const extra = el('details', undefined, col);
      el('summary', `나머지 ${ids.length - 20}개 펼치기`, extra);
      ids.slice(20).forEach(id => card(id, extra));
    }
  }
  for (let i = depth - 1; i >= 0; i--) lane(incoming[i], `${i + 1}단계 호출자 →`);
  lane([selected], '선택한 코드', true);
  for (let i = 0; i < depth; i++) lane(outgoing[i], `${i + 1}단계 호출 대상`);
  requestAnimationFrame(wires);
  lanes.addEventListener('toggle', () => requestAnimationFrame(wires), true);
}

function wires() {
  const lanes = document.querySelector('.lanes');
  if (!lanes) return;
  lanes.querySelector('.wires')?.remove();
  const ns = 'http://www.w3.org/2000/svg';
  function shape(tag, attrs, parent) {
    const node = document.createElementNS(ns, tag);
    for (const [key,value] of Object.entries(attrs)) node.setAttribute(key,value);
    parent.append(node); return node;
  }
  const drawing = shape('svg', {class:'wires',width:lanes.scrollWidth,height:lanes.scrollHeight,'aria-hidden':'true'}, lanes);
  const defs = shape('defs',{},drawing);
  const marker = shape('marker',{id:'flow-arrow',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:5,markerHeight:5,orient:'auto'},defs);
  shape('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:'#779fb5'},marker);
  const origin = lanes.getBoundingClientRect();
  const columns = [...lanes.querySelectorAll('.lane')];
  for (let i = 0; i < columns.length - 1; i++) {
    const left = [...columns[i].querySelectorAll('.card')].filter(n=>n.getClientRects().length);
    const right = [...columns[i+1].querySelectorAll('.card')].filter(n=>n.getClientRects().length);
    for (const a of left) for (const b of right) {
      if (!calls.some(e=>e.source === a.dataset.nodeId && e.target === b.dataset.nodeId)) continue;
      const ar=a.getBoundingClientRect(), br=b.getBoundingClientRect();
      const x1=ar.right-origin.left,y1=ar.top+ar.height/2-origin.top,x2=br.left-origin.left,y2=br.top+br.height/2-origin.top;
      shape('path',{d:`M ${x1} ${y1} C ${x1+18} ${y1}, ${x2-18} ${y2}, ${x2} ${y2}`,fill:'none',stroke:'#779fb5','stroke-width':1.5,'marker-end':'url(#flow-arrow)'},drawing);
    }
  }
}
function evidence() {
  const box = $('evidence'); box.replaceChildren();
  el('h3', '선택한 코드의 호출 후보와 근거', box);
  const edges = calls.filter(e => e.source === selected || e.target === selected);
  if (!edges.length) el('p', '확인된 내부 호출 관계가 없습니다.', box);
  for (const edge of edges) {
    const source = index.get(edge.source), target = index.get(edge.target);
    if (!source || !target) continue;
    const row = el('div', undefined, box); row.className = 'evidence-row';
    el('button', `${source.name} → ${target.name}`, row, () => choose(edge.source === selected ? edge.target : edge.source));
    el('button', `${source.file}:${edge.lineno || source.lineno || 1} ↗`, row, () => open(source, edge.lineno));
    const proof = edge.evidence || {};
    el('small', edge.type === 'calls_implicit' ? (IMPLICIT[proof.implicit_kind] || '암묵 호출 후보')
      : edge.type === 'instantiates' ? '생성자 후보' : '호출 후보', row);
    el('small', [proof.rule, proof.certainty].filter(Boolean).join(' · '), row);
  }
  const node = index.get(selected);
  const sites = (data.call_statuses || []).filter(c => node.type === 'file' ? c.file === node.file : c.caller_id === selected);
  const other = sites.filter(c => c.status !== 'RESOLVED_INTERNAL');
  if (other.length) {
    const group = el('details', undefined, box);
    el('summary', `외부·내장 및 미확정 호출 ${other.length}개`, group);
    el('p', '미확정은 내부 호출 누락을 뜻하지 않습니다. 호출 후보는 실제 실행을 보장하지 않습니다.', group);
    for (const site of other) {
      const row = el('div', undefined, group); row.className = 'evidence-row';
      el('button', `${site.callee_text} · ${site.file}:${site.line} ↗`, row, () => open(node, site.line));
      el('small', site.status === 'UNKNOWN' ? '미확정' : `외부·내장 (${site.origin_kind})`, row);
      el('small', site.evidence?.rule || '', row);
    }
  }
}
function commits(hashes, parent) {
  for (const hash of hashes) {
    const commit = data.history.commits.find(c => c.sha === hash);
    if (!commit) continue;
    const button = el('button', `${hash.slice(0,8)} · ${commit.subject}`, parent, () => api.postMessage({type:'commit',sha:hash}));
    button.className = 'commit'; button.title = commit.date;
  }
}
function history() {
  const node = index.get(selected), box = $('history'); box.replaceChildren();
  $('history-file').textContent = node.file;
  $('cochange-tab').setAttribute('aria-pressed', String(tab === 'cochange'));
  $('history-tab').setAttribute('aria-pressed', String(tab === 'history'));
  const h = data.history;
  if (!h.available) { el('p', 'Git 이력을 사용할 수 없습니다.', box); el('small', h.error || '', box); return; }
  el('p', `${node.changes}회 변경 · 최근 ${h.days}일 / 최대 ${h.limit}개 비병합 커밋`, box);
  if (tab === 'history') {
    const hashes = h.commits.filter(c => c.files.includes(node.file)).map(c => c.sha);
    if (!hashes.length) el('p', '관찰 범위에 변경 이력이 없습니다.', box);
    commits(hashes, box); return;
  }
  const pairs = data.edges.filter(e => e.type === 'cochange' && (e.source === 'file:' + node.file || e.target === 'file:' + node.file)).sort((a,b) => b.count - a.count);
  el('small', `2회 이상 함께 변경된 현재 Python 파일. 50파일 초과 커밋 ${h.skipped_large_commits}개 제외. 파일 이름 변경은 추적하지 않습니다.`, box);
  if (!pairs.length) el('p', '관찰 범위에 반복된 공동 변경이 없습니다.', box);
  for (const pair of pairs) {
    const other = index.get(pair.source === 'file:' + node.file ? pair.target : pair.source);
    if (!other) continue;
    const group = el('article', undefined, box); group.className = 'cochange-card';
    el('button', other.file, group, () => choose(other.id)).className = 'file-link';
    const meter = el('progress', undefined, group); meter.max = pairs[0].count; meter.value = pair.count;
    el('span', ` ${pair.count}회`, group);
    const details = el('details', undefined, group); el('summary', '공동 변경 커밋 보기', details); commits(pair.commits, details);
  }
  el('small', '공동 변경은 함께 살펴볼 단서이며 호출 관계나 인과관계를 뜻하지 않습니다.', box);
}
function render() {
  const node = index.get(selected); if (!node) return;
  $('focus').replaceChildren();
  el('small', 'CURRENT FOCUS', $('focus'));
  el('h1', node.class_name ? `${node.class_name}.${node.name}` : node.name, $('focus'));
  el('p', `${node.file}:${node.lineno || 1} · 서로 다른 호출자 ${node.callers}개 · 저장된 소스 기준`, $('focus'));
  $('depth').textContent = `${depth}단계`;
  $('less').disabled = depth <= 1; $('more').disabled = depth >= 3;
  $('back').disabled = !trail.length;
  tree(); flow(); evidence(); history(); renderGitValidation();
}

// KnitCode Git Validation UI PATCH v1. Render source-derived text, never HTML.
function renderGitValidation() {
  const box = $('git-validation-panel');
  if (!box) return;
  box.replaceChildren();
  if (!gitValidation) return;
  if (!gitValidation.available) {
    el('p', 'Git 저장소 정보가 없습니다. ZIP 대신 git clone으로 받은 프로젝트를 열어주세요.', box);
    if (gitValidation.error) el('small', gitValidation.error, box);
    return;
  }
  const node = index.get(selected);
  el('p', `분석 커밋 ${gitValidation.analyzed_commits}개 · 작성자 ${gitValidation.authors.length}명`, box);
  const record = node && gitValidation.files[node.file];
  if (!record) {
    el('p', '선택된 파일의 커밋 변경 이력이 없거나 분석 범위 밖입니다.', box);
    return;
  }
  el('strong', `${record.commits}개 커밋에서 변경된 파일`, box);
  const authors = el('details', undefined, box);
  el('summary', `수정 작성자 ${record.authors.length}명 보기`, authors);
  record.authors.forEach(a => el('p', `${a.name} · ${a.count}개 커밋`, authors));
  const kinds = Object.entries(record.types).map(([kind, count]) => `${kind}: ${count}`).join(' / ');
  el('p', `수정 유형(커밋 메시지 추정): ${kinds || '없음'}`, box);
  const fn = el('details', undefined, box);
  el('summary', `변경된 함수 핫스팟 ${record.functions.length}개`, fn);
  record.functions.forEach(f => el('p', `${f.name} · ${f.count}회`, fn));
  const joint = el('details', undefined, box);
  el('summary', `동시 수정 파일 ${record.cochanges.length}개`, joint);
  record.cochanges.forEach(f => el('p', `${f.file} · ${f.count}회 (관측 비율 ${(f.confidence*100).toFixed(0)}%)`, joint));
  // Cross-reference the team's call graph with Git co-change evidence.
  const structural = new Set();
  for (const edge of data.edges) {
    if (!['calls', 'instantiates'].includes(edge.type)) continue;
    const from = index.get(edge.source), to = index.get(edge.target);
    if (!from || !to) continue;
    if (from.file === node.file && to.file !== node.file) structural.add(to.file);
    if (to.file === node.file && from.file !== node.file) structural.add(from.file);
  }
  const overlap = record.cochanges.filter(f => structural.has(f.file));
  if (overlap.length) {
    const both = el('details', undefined, box);
    el('summary', `호출 관계 + 공동변경 근거가 모두 있는 파일 ${overlap.length}개`, both);
    overlap.forEach(f => el('p', `${f.file} · 공동변경 ${f.count}회 · 정적 호출 경로 관측`, both));
  }
  el('small', gitValidation.note, box);
}
$('git-validation-run').addEventListener('click', () => api.postMessage({type:'gitValidationRun'}));
$('git-validation-report').addEventListener('click', () => api.postMessage({type:'gitValidationReport'}));
$('search').addEventListener('input', () => { if (data) tree(); });
$('more').addEventListener('click', () => { if (data && depth < 3) { depth++; render(); } });
$('less').addEventListener('click', () => { if (data && depth > 1) { depth--; render(); } });
$('back').addEventListener('click', () => { if (trail.length) choose(trail.pop(), false); });
$('refresh').addEventListener('click', () => api.postMessage({type:'refresh'}));
$('cochange-tab').addEventListener('click', () => { tab='cochange'; if(selected)history(); });
$('history-tab').addEventListener('click', () => { tab='history'; if(selected)history(); });
window.addEventListener('message', ({data:message}) => {
  if (message.type === 'gitValidationStatus') $('git-validation-status').textContent = message.text;
  if (message.type === 'gitValidation') { gitValidation = message.data;
    $('git-validation-status').textContent = gitValidation.available ? 'Git 분석 완료' : 'Git 이력 없음';
    renderGitValidation(); return; }
  if (message.type === 'status') $('status').textContent = message.text;
  if (message.type !== 'data') return;
  data = message.data;
  index = new Map(data.nodes.map(n => [n.id,n]));
  calls = data.edges.filter(e => ['calls','calls_override','instantiates','calls_implicit'].includes(e.type));
  const s = data.summary;
  const counts = data.status_summary?.statuses || {};
  const cutoffs = data.flow?.recursion_or_budget_cutoffs || 0;
  $('status').textContent = `${s.files} Python 파일 · 내부 호출 ${counts.RESOLVED_INTERNAL || 0} · 외부·내장 ${counts.KNOWN_NON_INTERNAL || 0} · 미확정 ${counts.UNKNOWN || 0} · 저장된 소스의 정적 후보${data.warnings.length ? ' · 파싱 제외: '+data.warnings.join('; ') : ''}${cutoffs ? ` · 재귀·계산 한도에서 보수적 처리 ${cutoffs}회` : ''}`;
  const initial = data.nodes.find(n => n.file === message.initialFile && ['function','method'].includes(n.type)) || data.nodes.find(n => ['function','method'].includes(n.type)) || data.nodes[0];
  trail = trail.filter(id => index.has(id));
  if (initial) choose(index.has(selected) ? selected : initial.id, false);
  else {
    selected = undefined; tree();
    for (const id of ['focus','flow','evidence','history','history-file']) $(id).replaceChildren();
    el('p', '분석할 Python 코드가 없습니다.', $('flow'));
  }
});
api.postMessage({type:'ready'});

window.addEventListener('resize', () => requestAnimationFrame(wires));

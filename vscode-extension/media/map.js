/* Project content is rendered only as text. No project scripts are executed. */
const api = acquireVsCodeApi();
const $ = id => document.getElementById(id);
let data, selected, depth = 1, tab = 'cochange', trail = [];
let gitValidation;
let authorFilter = '';
let index = new Map(), calls = [];
const COMMIT_TYPES = {feature: '기능 추가', bugfix: '버그 수정', refactor: '리팩터링', test: '테스트', docs: '문서', chore: '빌드·설정', unknown: '분류 안 됨'};
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
// pytest-style discovery: tests/ or test/ folders, test_*.py or *_test.py files.
const isTest = node => /(^|\/)tests?\//.test(node.file) || /(^|\/)(test_[^/]*|[^/]*_test)\.py$/.test(node.file);
function layers(id, incoming, limit, skip) {
  const seen = new Set([id]), result = [];
  let frontier = [id];
  for (let step = 0; step < limit; step++) {
    const next = new Set();
    for (const edge of calls) {
      const from = incoming ? edge.target : edge.source;
      const to = incoming ? edge.source : edge.target;
      if (frontier.includes(from) && !seen.has(to) && index.has(to) && !skip?.(index.get(to))) next.add(to);
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
// node id -> commits that changed that function, from Git Validation. Rebuilt when either input reloads.
let changeCounts;
function functionChanges() {
  if (changeCounts || !gitValidation?.available || !data) return changeCounts;
  changeCounts = new Map();
  for (const [file, record] of Object.entries(gitValidation.files)) {
    const counts = new Map();
    for (const event of record.events || []) for (const name of event.functions) counts.set(name, (counts.get(name) || 0) + 1);
    const members = data.nodes.filter(n => n.file === file && ['function','method'].includes(n.type));
    for (const [name, count] of counts) {
      // Same rule as the hotspot list: only a unique match is linked to a card.
      const matches = members.filter(n => n.name === name || n.name.endsWith('.' + name));
      if (matches.length === 1) changeCounts.set(matches[0].id, count);
    }
  }
  return changeCounts;
}
function card(id, parent, center = false) {
  const node = index.get(id);
  const box = el('article', undefined, parent); box.className = 'card' + (center ? ' center' : ''); box.dataset.nodeId = id;
  el('small', node.type.toUpperCase(), box);
  const changes = functionChanges()?.get(id);
  if (changes) {
    box.className += ' changed';
    // Fixed steps (1, 2, 3+ commits) keep the same meaning while navigating.
    box.style.setProperty('--heat-level', String(Math.min(changes, 3) / 3));
    const badge = el('span', `변경 ${changes}회`, box);
    badge.className = 'change-badge';
    badge.title = `최근 ${gitValidation.analyzed_commits}개 커밋 중 이 함수를 바꾼 커밋 수`;
  }
  el('button', node.class_name ? `${node.class_name}.${node.name}` : node.name, box, () => choose(id)).className = 'node-name';
  el('p', `${node.file}:${node.lineno || 1}`, box);
  const actions = el('div', undefined, box); actions.className = 'actions';
  el('button', '코드 ↗', actions, () => open(node));
  if (!center) el('button', '중심으로', actions, () => choose(id));
}
function flow() {
  const box = $('flow'); box.replaceChildren();
  const node = index.get(selected);
  // Step counts only mean something in the call flow, not on a file's graph.
  $('flow-controls').hidden = mapMode || node.type === 'file';
  if (node.type === 'file') {
    // A file shows its functions as a call graph; a function then opens the usual call flow.
    if (data.nodes.some(n => n.file === node.file && ['function', 'method', 'class'].includes(n.type))) renderFileGraph(node, box);
    else el('p', '이 파일에는 분석된 함수·클래스가 없습니다.', box);
    return;
  }
  // Tests calling the focus are listed apart so they do not crowd the program flow.
  const skip = isTest(node) ? undefined : isTest;
  const incoming = layers(selected, true, depth, skip), outgoing = layers(selected, false, depth);
  const testCallers = skip ? [...new Set(calls.filter(e => e.target === selected && index.has(e.source)
    && isTest(index.get(e.source))).map(e => e.source))].sort() : [];
  const lanes = el('div', undefined, box); lanes.className = 'lanes';
  function lane(ids, title, center = false, tests = []) {
    const col = el('section', undefined, lanes); col.className = 'lane';
    el('h3', title, col);
    if (!ids.length) el('p', tests.length ? '테스트 외 내부 호출자 없음' : '확인된 내부 호출 없음', col).className = 'empty';
    ids.slice(0, 20).forEach(id => card(id, col, center));
    if (ids.length > 20) {
      const extra = el('details', undefined, col);
      el('summary', `나머지 ${ids.length - 20}개 펼치기`, extra);
      ids.slice(20).forEach(id => card(id, extra));
    }
    if (tests.length) {
      const group = el('details', undefined, col); group.className = 'test-callers';
      el('summary', `🧪 이 함수를 직접 호출하는 테스트 ${tests.length}개`, group);
      tests.forEach(id => {
        const test = index.get(id);
        const button = el('button', `${test.name} ↗`, group, () => open(test));
        button.className = 'test-caller'; button.title = `${test.file}:${test.lineno || 1}`;
      });
    }
  }
  for (let i = depth - 1; i >= 0; i--) lane(incoming[i], `${i + 1}단계 호출자 →`, false, i === 0 ? testCallers : []);
  lane([selected], '선택한 코드', true);
  for (let i = 0; i < depth; i++) lane(outgoing[i], `${i + 1}단계 호출 대상`);
    requestAnimationFrame(wires);
    lanes.addEventListener('toggle', () => requestAnimationFrame(wires), true);
    if (functionChanges()?.size) el('small', `주황 테두리·배지: 최근 ${gitValidation.analyzed_commits}개 커밋에서 함수가 바뀐 횟수 (연함 1회 · 중간 2회 · 진함 3회 이상)`, box).className = 'change-legend';
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
// Step C: pair the arguments written at a call site with the callee's parameters (declared hints only).
// Split on top-level commas, ignoring commas inside brackets and strings.
function splitTop(text) {
  const parts = []; let depth = 0, quote = null, start = 0;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quote) { if (ch === '\\') i++; else if (ch === quote) quote = null; continue; }
    if (ch === '"' || ch === "'") quote = ch;
    else if ('([{'.includes(ch)) depth++;
    else if (')]}'.includes(ch)) depth--;
    else if (ch === ',' && depth === 0) { parts.push(text.slice(start, i)); start = i + 1; }
  }
  parts.push(text.slice(start));
  return parts.map(p => p.trim()).filter(Boolean);
}
// Text between the first "(" and its matching ")", or null.
function insideParens(text) {
  const open = text.indexOf('(');
  if (open < 0) return null;
  let depth = 0, quote = null;
  for (let i = open; i < text.length; i++) {
    const ch = text[i];
    if (quote) { if (ch === '\\') i++; else if (ch === quote) quote = null; continue; }
    if (ch === '"' || ch === "'") quote = ch;
    else if (ch === '(') depth++;
    else if (ch === ')' && --depth === 0) return text.slice(open + 1, i);
  }
  return null;
}
function parseParams(signature) {
  const inner = insideParens(signature || '');
  if (inner == null) return null;
  return splitTop(inner).map(p => {
    const star = p.match(/^\*{0,2}/)[0];
    const [head, def] = splitDefault(p.slice(star.length));
    const colon = head.indexOf(':');
    return {star, name: (colon < 0 ? head : head.slice(0, colon)).trim(),
            hint: colon < 0 ? '' : head.slice(colon + 1).trim(), default: def};
  });
}
// "x: int=3" -> ["x: int", "3"]; an "=" inside brackets of the hint does not count.
function splitDefault(text) {
  let depth = 0;
  for (let i = 0; i < text.length; i++) {
    if ('([{'.includes(text[i])) depth++;
    else if (')]}'.includes(text[i])) depth--;
    else if (text[i] === '=' && depth === 0 && text[i + 1] !== '=') return [text.slice(0, i).trim(), text.slice(i + 1).trim()];
  }
  return [text.trim(), null];
}
// Arguments of the call that the edge points at: the last call in a chain such as a(x).b(y) is b(y).
function callArguments(source) {
  const text = source.trimEnd();
  if (!text.endsWith(')')) return insideParens(text);
  let depth = 0, quote = null;
  for (let i = text.length - 1; i >= 0; i--) {
    const ch = text[i];
    if (quote) { if (ch === quote && text[i - 1] !== '\\') quote = null; continue; }
    if (ch === '"' || ch === "'") quote = ch;
    else if (ch === ')') depth++;
    else if (ch === '(' && --depth === 0) return text.slice(i + 1, -1);
  }
  return null;
}
// Returns rows {arg, param, hint, note}; null when the call text or signature cannot be read.
function bindArguments(edge, callee) {
  let target = callee;
  if (edge.type === 'instantiates') target = index.get(callee.id.replace(/^CLASS:/, 'METHOD:') + '.__init__');
  const meta = target?.navigation_metadata || {};
  const params = parseParams(meta.signature), argText = callArguments(edge.evidence?.source || '');
  if (!params || argText == null) return null;
  // A method reached through an instance or class receives self/cls implicitly.
  if (target.type === 'method' && ['instance', 'class'].includes(meta.kind) && !params[0]?.star) params.shift();
  const visible = params.filter(p => p.name && p.name !== '/' && !(p.star === '*' && !p.name));
  const rows = [], used = new Set();
  const positional = params.filter(p => !p.star).slice(0, params.findIndex(p => p.star) >= 0 ? params.findIndex(p => p.star) : undefined);
  const varargs = params.find(p => p.star === '*' && p.name), kwargs = params.find(p => p.star === '**');
  let at = 0;
  const args = splitTop(argText), unpacked = args.some(a => a.startsWith('*'));
  for (const arg of args) {
    if (arg.startsWith('**') || (arg.startsWith('*') && !arg.startsWith('**'))) { rows.push({arg, param: '', hint: '', note: '펼쳐서 전달 · 매개변수 대응 불확실'}); continue; }
    const kw = arg.match(/^([A-Za-z_]\w*)\s*=(?!=)\s*([\s\S]*)$/);
    if (kw) {
      const p = visible.find(x => x.name === kw[1] && !x.star);
      if (p) { used.add(p); rows.push({arg: kw[2], param: p.name, hint: p.hint, note: '키워드'}); }
      else rows.push({arg: kw[2], param: kwargs ? `**${kwargs.name}` : kw[1], hint: '', note: kwargs ? '키워드 → 나머지 키워드 인자' : '맞는 매개변수 없음'});
      continue;
    }
    const p = positional[at++];
    if (p) { used.add(p); rows.push({arg, param: p.name, hint: p.hint, note: ''}); }
    else rows.push({arg, param: varargs ? `*${varargs.name}` : '?', hint: '', note: varargs ? '나머지 위치 인자' : '매개변수보다 인자가 많음'});
  }
  for (const p of visible) if (!used.has(p) && !p.star && p.default != null) rows.push({arg: '', param: p.name, hint: p.hint, note: `기본값 ${p.default}`});
  for (const p of visible) if (!used.has(p) && !p.star && p.default == null)
    rows.push({arg: '', param: p.name, hint: p.hint, note: unpacked ? '펼친 인자에서 올 수 있음' : '값이 넘어오지 않음 · 확인 필요'});
  return rows;
}
function argumentTable(edge, callee, parent) {
  const rows = bindArguments(edge, callee);
  if (!rows) { el('small', '전달값: 받는 함수의 시그니처를 읽을 수 없습니다.', parent).className = 'args-none'; return; }
  const box = el('div', undefined, parent); box.className = 'args';
  if (!rows.length) { el('small', '전달값 없음 (인자 없이 호출)', box); return; }
  el('small', '넘기는 값 → 받는 매개변수 (타입은 선언된 힌트)', box).className = 'args-title';
  for (const r of rows) {
    const line = el('div', undefined, box);
    line.className = 'args-row' + (/불확실|확인 필요|없음|많음/.test(r.note) ? ' warn' : '');
    el('code', r.arg || '—', line);
    el('span', '→', line);
    el('code', r.param + (r.hint ? `: ${r.hint}` : ''), line);
    if (r.note) el('small', r.note, line);
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
    if (['calls', 'instantiates'].includes(edge.type)) argumentTable(edge, target, row);
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
  updateGitTabs();
  if (tab === 'insights') return;
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
  // Same edge types as node.callers (calls, instantiates), so the test share never exceeds the total.
  const testCallerCount = isTest(node) ? 0 : new Set(calls.filter(e => e.target === node.id && ['calls','instantiates'].includes(e.type)
    && index.has(e.source) && isTest(index.get(e.source))).map(e => e.source)).size;
  el('p', `${node.file}:${node.lineno || 1} · 서로 다른 호출자 ${node.callers}개${testCallerCount ? ` (테스트 ${testCallerCount}개)` : ''} · 저장된 소스 기준`, $('focus'));
  $('depth').textContent = `${depth}단계`;
  $('less').disabled = depth <= 1; $('more').disabled = depth >= 3;
  $('back').disabled = !trail.length;
  tree(); flow(); evidence(); history(); renderGitValidation(); renderWorkingChanges();
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
  const label = el('label', '작성자별 함수·커밋 보기', box);
  const filter = el('select', undefined, label);
  filter.setAttribute('aria-label', '작성자 필터');
  const all = el('option', '모든 작성자', filter); all.value = '';
  const availableAuthors = [...new Set((record.events || []).map(e => e.author))];
  if (!availableAuthors.includes(authorFilter)) authorFilter = '';
  for (const author of availableAuthors) { const option = el('option', author, filter); option.value = author; }
  filter.value = authorFilter;
  filter.addEventListener('change', () => { authorFilter = filter.value; renderGitValidation(); });
  const events = (record.events || []).filter(e => !authorFilter || e.author === authorFilter);
  el('p', `선택 범위: ${events.length}개 커밋`, box);
  // Estimated from commit-message rules; follows the author filter like the hotspots below.
  const typeCounts = new Map();
  for (const event of events) typeCounts.set(event.type, (typeCounts.get(event.type) || 0) + 1);
  el('small', '수정 유형 (커밋 메시지로 추정)', box);
  const types = el('div', undefined, box); types.className = 'type-chips';
  [...typeCounts].sort((a, b) => (a[0] === 'unknown') - (b[0] === 'unknown') || b[1] - a[1]).forEach(([kind, count]) => {
    el('span', `${COMMIT_TYPES[kind] || kind} ${count}`, types).className = 'type-chip' + (kind === 'unknown' ? ' muted' : '');
  });
  const hot = new Map();
  for (const event of events) for (const name of event.functions) hot.set(name, (hot.get(name) || 0) + 1);
  const hotspots = [...hot].sort((a,b) => b[1] - a[1]).map(([name,count]) => ({name,count}));
  const fn = el('details', undefined, box);
  fn.open = true;
  el('summary', `변경된 함수 핫스팟 ${hotspots.length}개`, fn);
  if (!hotspots.length) el('p', '선택한 커밋에서 바뀐 함수가 없습니다. 모듈 수준 코드나 주석·공백만 바뀐 커밋일 수 있습니다.', fn).className = 'empty';
    // One scale for every author filter: the file's most-changed function across all authors.
  const allCounts = new Map();
  for (const event of record.events || []) for (const name of event.functions) allCounts.set(name, (allCounts.get(name) || 0) + 1);
  const most = Math.max(1, ...allCounts.values());
  const hotspotRow = (f, parent) => {
    const matches = data.nodes.filter(n => n.file === node.file && ['function','method'].includes(n.type)
      && (n.name === f.name || n.name.endsWith('.' + f.name)));
    const linked = matches.length === 1;
    const row = el(linked ? 'button' : 'div', undefined, parent, linked ? () => { choose(matches[0].id); open(matches[0]); } : undefined);
    row.className = 'hotspot' + (linked ? '' : ' unmatched');
    row.title = linked ? '호출 흐름 중심으로 선택하고 코드 열기' : '현재 소스에서 위치 확인 불가';
    el('span', f.name, row).className = 'hotspot-name';
    const bar = el('span', undefined, row);
    bar.className = 'hotspot-bar';
    bar.style.setProperty('--ratio', String(f.count / most));
    el('span', `${f.count}회`, row).className = 'hotspot-count';
  };
  hotspots.slice(0, 10).forEach(f => hotspotRow(f, fn));
  if (hotspots.length > 10) {
    const more = el('details', undefined, fn);
    more.className = 'hotspot-more';
    el('summary', `나머지 ${hotspots.length - 10}개 펼치기`, more);
    hotspots.slice(10).forEach(f => hotspotRow(f, more));
  }
  const eventList = el('details', undefined, box);
  el('summary', '선택 작성자의 커밋', eventList);
  events.forEach(event => el('p', `${event.sha.slice(0,8)} · ${event.author} · ${COMMIT_TYPES[event.type] || event.type}`, eventList));
  const joint = el('details', undefined, box);
  el('summary', `동시 수정 파일 ${record.cochanges.length}개 (전체 작성자 기준)`, joint);
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
    el('summary', `호출 관계 + 공동변경 근거가 모두 있는 파일 ${overlap.length}개 (전체 작성자 기준)`, both);
    overlap.forEach(f => el('p', `${f.file} · 공동변경 ${f.count}회 · 정적 호출 경로 관측`, both));
  }
  el('small', gitValidation.note, box);
}
function renderWorkingChanges() {
  const box = $('working-changes'); box.replaceChildren();
  el('h3', '미커밋 변경 영향 후보', box);
  const changes = data?.working_changes;
  if (!changes?.available) { el('p', changes?.error || 'Git 변경 정보를 사용할 수 없습니다.', box); return; }
  el('small', changes.basis, box);
  if (!changes.files.length) el('p', '저장된 Python 변경이 없습니다.', box);
  for (const warning of changes.warnings) el('p', warning, box);
  for (const file of changes.files) {
    const group = el('details', undefined, box);
    el('summary', `${file.file} · ${file.functions.length}개 함수 변경`, group);
    if (file.error) el('p', `분석 제외: ${file.error}`, group);
    if (!file.error && !file.functions.length) el('p', '함수 AST 변경 없음. 주석·공백·모듈 수준 변경일 수 있습니다.', group);
    for (const fn of file.functions) {
      const node = index.get(fn.node_id);
      const kind = {added:'추가', modified:'수정', deleted:'삭제'}[fn.kind];
      if (node) el('button', `${fn.name} · ${kind} ↗`, group, () => { choose(node.id); open(node); }).className = 'commit';
      else el('p', `${fn.name} · ${kind} · 현재 위치 연결 불가`, group);
      el('small', fn.facts.join(' · '), group);
      if (!node) el('p', '삭제·이름 변경 함수의 이전 호출자는 현재 그래프로 확인할 수 없습니다.', group);
      else if (!fn.callers.length) el('p', '현재 그래프에서 확인된 직접 호출자 없음', group);
      for (const id of fn.callers) {
        const caller = index.get(id);
        if (caller) el('button', `호출자: ${caller.name} ↗`, group, () => { choose(id); open(caller); }).className = 'commit';
      }
    }
    const pairs = data.history.pairs.filter(p => p.source === file.file || p.target === file.file);
    if (pairs.length) el('p', '함께 검토할 공동 변경 파일', group);
    for (const pair of pairs) {
      const other = pair.source === file.file ? pair.target : pair.source;
      const node = data.nodes.find(n => n.type === 'file' && n.file === other);
      if (node) el('button', `${other} · ${pair.commits.length}회`, group, () => choose(node.id)).className = 'commit';
      else el('p', other, group);
    }
  }
  el('small', '직접 호출자와 공동 변경은 검토 후보입니다. 실행 영향·전이 영향·삭제 전 호출 관계를 보장하지 않습니다. 저장 후 재분석하세요.', box);
}
$('git-validation-run').addEventListener('click', () => api.postMessage({type:'gitValidationRun'}));
$('git-validation-report').addEventListener('click', () => api.postMessage({type:'gitValidationReport'}));
$('search').addEventListener('input', () => { if (data) tree(); });
$('more').addEventListener('click', () => { if (data && depth < 3) { depth++; render(); } });
$('less').addEventListener('click', () => { if (data && depth > 1) { depth--; render(); } });
$('back').addEventListener('click', () => { if (trail.length) choose(trail.pop(), false); });
$('refresh').addEventListener('click', () => api.postMessage({type:'refresh'}));

// Step 1 of the overview: the project map is the first screen; a file opens the existing function view.
let mapMode = true;
function showMap(on) {
  mapMode = on;
  for (const id of ['focus', 'flow-controls', 'flow', 'evidence']) $(id).hidden = on;
  $('project-map').hidden = !on;
  $('toggle-map').textContent = on ? '함수 화면 보기' : '프로젝트 지도';
  $('toggle-map').setAttribute('aria-pressed', String(on));
  if (on) renderMap();
}
// Step 2 of the overview: aggregate the function-level analysis into one record per file.
const OTHER_FILE = /^(docs?|examples?|scripts?|benchmarks?)\/|^setup\.py$/;
const CALL_TYPES = ['calls', 'calls_override', 'instantiates', 'calls_implicit'];
const LINK_TYPES = [...CALL_TYPES, 'imports', 'inherits', 'references'];
function buildProjectMap(limit) {
  const files = new Map();
  for (const n of data.nodes) if (n.type === 'file') files.set(n.file, {
    id: n.id, path: n.file, name: n.file.split('/').pop(), changes: data.history.changes?.[n.file] || 0, funcs: 0,
    group: isTest(n) ? 'test' : OTHER_FILE.test(n.file) ? 'other' : 'code', depth: null, rank: null, entry: []});
  for (const n of data.nodes) if (['function', 'method'].includes(n.type) && files.has(n.file)) files.get(n.file).funcs++;
  const moduleFile = new Map(data.nodes.filter(n => n.type === 'module').map(n => [n.id, n.file]));
  for (const m of data.reading_order?.modules || []) {
    const f = files.get(moduleFile.get(m.id));
    if (f) Object.assign(f, {depth: m.min_depth ?? null, rank: m.rank ?? null, entry: m.entry || []});
  }
  // Calls keep direction (a -> b); "linked" is any code relation either way, used to spot hidden coupling.
  const fileOf = new Map(data.nodes.map(n => [n.id, n.file]));
  const calls = new Map(), linked = new Set();
  for (const e of data.edges) {
    const a = fileOf.get(e.source), b = fileOf.get(e.target);
    if (!a || !b || a === b) continue;
    if (CALL_TYPES.includes(e.type)) calls.set(a + '\n' + b, (calls.get(a + '\n' + b) || 0) + 1);
    if (LINK_TYPES.includes(e.type)) linked.add([a, b].sort().join('\n'));
  }
  // Co-change counts only commits touching 2..limit files; bulk commits (type hints, moves) add noise.
  const pairs = new Map();
  for (const c of data.history.commits || []) {
    if (c.files.length < 2 || c.files.length > limit) continue;
    for (let x = 0; x < c.files.length; x++) for (let y = x + 1; y < c.files.length; y++) {
      const key = [c.files[x], c.files[y]].sort().join('\n');
      pairs.set(key, (pairs.get(key) || 0) + 1);
    }
  }
  const cochange = [...pairs].filter(([, n]) => n >= 2).map(([key, n]) => {
    const [a, b] = key.split('\n');
    return {a, b, count: n, hidden: !linked.has(key)};
  });
  return {files, calls: [...calls].map(([key, n]) => { const [a, b] = key.split('\n'); return {a, b, count: n}; }), cochange};
}
// Step 3: one column per distance from the entry points; colour = how often the file changed.
// Test and other files get their own columns, shown only on request.
const MAP_COLUMNS = [
  ['진입점', '공개 API · 실행 시작', f => f.group === 'code' && f.depth === 0],
  ['1걸음', '진입점이 바로 호출', f => f.group === 'code' && f.depth === 1],
  ['2걸음', '', f => f.group === 'code' && f.depth === 2],
  ['3걸음 이상', '', f => f.group === 'code' && f.depth >= 3],
  ['호출로 닿지 않음', '설정·버전·호환 코드', f => f.group === 'code' && f.depth == null],
  ['테스트', '', f => f.group === 'test', true],
  ['기타', 'docs · setup', f => f.group === 'other', true],
];
let mapShowTests = false, mapLimit = 6;
const HEAT = [[0, 0, '0'], [1, 2, '1–2'], [3, 5, '3–5'], [6, 10, '6–10'], [11, Infinity, '11+']];
const heatOf = n => HEAT.findIndex(([lo, hi]) => n >= lo && n <= hi);
function svgEl(tag, attrs, parent, text) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  parent.append(node);
  return node;
}
// Pan and zoom shared by the project map and the file graph; each keeps its own state object.
const mapZoom = {view: null, dragged: false, startWide: true}, fileZoom = {view: null, dragged: false, file: null};
function setupZoom(zoom, svg, view, width, height, controls) {
  const apply = () => { view.setAttribute('transform', `translate(${zoom.view.x} ${zoom.view.y}) scale(${zoom.view.k})`); zoom.onZoom?.(zoom.view.k); };
  // "whole" fits everything; otherwise only the width, so a tall map opens readable at the top.
  const fit = (whole = true) => {
    const w = svg.clientWidth, h = svg.clientHeight;
    const k = w && h ? Math.min(w / (width + 20), whole ? h / (height + 20) : Infinity, 1.5) : 1;
    zoom.view = {k, x: 10, y: 10}; apply();
  };
  // Zoom around a point (the cursor or the centre) so that point stays where it is.
  const zoomAt = (factor, cx, cy) => {
    const v = zoom.view, k = Math.min(3, Math.max(.3, v.k * factor));
    zoom.view = {k, x: cx - (cx - v.x) * k / v.k, y: cy - (cy - v.y) * k / v.k}; apply();
  };
  if (zoom.view) apply(); else fit(!zoom.startWide);
  svg.addEventListener('wheel', event => {
    event.preventDefault();
    const box = svg.getBoundingClientRect();
    zoomAt(event.deltaY < 0 ? 1.15 : 1 / 1.15, event.clientX - box.left, event.clientY - box.top);
  }, {passive: false});
  let drag = null;
  svg.addEventListener('pointerdown', event => {
    zoom.dragged = false;
    if (event.button === 0) drag = {x: event.clientX, y: event.clientY, vx: zoom.view.x, vy: zoom.view.y, moved: false};
  });
  svg.addEventListener('pointermove', event => {
    if (!drag) return;
    const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
    if (!drag.moved && Math.hypot(dx, dy) < 4) return;
    if (!drag.moved) { drag.moved = true; svg.setPointerCapture(event.pointerId); svg.classList.toggle('panning', true); }
    zoom.view = {...zoom.view, x: drag.vx + dx, y: drag.vy + dy}; apply();
  });
  // A drag that started on a box must not also open it.
  const end = () => { if (drag?.moved) zoom.dragged = true; drag = null; svg.classList.toggle('panning', false); };
  svg.addEventListener('pointerup', end);
  svg.addEventListener('pointercancel', end);
  const center = () => [svg.clientWidth / 2, svg.clientHeight / 2];
  controls.zoomIn.addEventListener('click', () => zoomAt(1.25, ...center()));
  controls.zoomOut.addEventListener('click', () => zoomAt(1 / 1.25, ...center()));
  controls.fit.addEventListener('click', () => fit(true));
}
function zoomControls(parent) {
  const zoom = el('span', undefined, parent); zoom.className = 'map-zoom';
  const controls = {zoomOut: el('button', '−', zoom), zoomIn: el('button', '+', zoom), fit: el('button', '전체 보기', zoom)};
  controls.zoomOut.setAttribute('aria-label', '축소'); controls.zoomIn.setAttribute('aria-label', '확대');
  return controls;
}

// Project map, function level: every function is a node, drawn inside the box of the file it belongs to.
// Boxes keep the column layout (distance from entry points); zooming out hides names and shows file-level lines.
const BW = 230, BCOL = 290, BHEAD = 40, BROW = 22, BPAD = 8, BGAP = 18, BTOP = 52, FAR = .6;
let mapItems = new Map(), mapLines = [];
function mapFocus(id) {
  const near = new Set(id ? [id] : []);
  for (const line of mapLines) {
    const on = !!id && (line.a === id || line.b === id);
    if (on) { near.add(line.a); near.add(line.b); }
    line.node.classList.toggle('near', on);
  }
  for (const [key, g] of mapItems) g.classList.toggle('near', near.has(key));
  document.querySelector('.project-map')?.classList.toggle('dim', !!id);
}
function renderMap() {
  const box = $('project-map'); box.replaceChildren();
  if (!data) { el('p', '분석이 끝나면 지도가 나타납니다.', box); return; }
  const map = buildProjectMap(mapLimit), changes = functionChanges();
  el('h2', '프로젝트 지도', box);
  el('p', '상자 안의 줄 하나가 함수 하나이고, 상자는 그 함수가 속한 파일입니다. 왼쪽 열일수록 진입점에 가깝고, 상자 머리 색이 진할수록 자주 바뀐 파일입니다. 확대하면 함수 이름과 함수 간 호출이, 축소하면 파일 간 관계가 보입니다.', box).className = 'map-lede';
  const options = el('div', undefined, box); options.className = 'map-options';
  const testsLabel = el('label', undefined, options);
  const tests = el('input', undefined, testsLabel); tests.type = 'checkbox'; tests.checked = mapShowTests;
  el('span', '테스트·기타 파일', testsLabel);
  tests.addEventListener('change', () => { mapShowTests = tests.checked; renderMap(); });
  const limitLabel = el('label', '함께 변경 집계 ', options);
  const limit = el('select', undefined, limitLabel);
  for (const [value, text] of [[6, '작은 커밋만 (파일 6개 이하)'], [50, '함께 변경 탭과 같은 기준 (파일 50개 이하)']]) {
    const option = el('option', text, limit); option.value = String(value);
  }
  limit.value = String(mapLimit);
  limit.addEventListener('change', () => { mapLimit = Number(limit.value); renderMap(); });
  const controls = zoomControls(options);

  const cols = MAP_COLUMNS.filter(([, , , extra]) => mapShowTests || !extra).map(([title, sub, test]) => ({title, sub,
    files: [...map.files.values()].filter(test).sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99) || b.changes - a.changes)}));
  const shownFiles = new Set(cols.flatMap(c => c.files.map(f => f.path)));
  // Function nodes: functions, methods and classes of the shown files that take part in at least one call.
  const fnCalls = calls.filter(e => index.has(e.source) && index.has(e.target) && e.source !== e.target
    && shownFiles.has(index.get(e.source).file) && shownFiles.has(index.get(e.target).file)
    && ['function', 'method', 'class'].includes(index.get(e.source).type) && ['function', 'method', 'class'].includes(index.get(e.target).type));
  const linked = new Set(fnCalls.flatMap(e => [e.source, e.target]));
  const fnsOf = path => data.nodes.filter(n => n.file === path && ['function', 'method', 'class'].includes(n.type));

  // Layout: boxes stacked per column; rows are the linked functions, most changed first, then source order.
  const pos = new Map(), boxes = [];
  let bottom = 0;
  cols.forEach((col, c) => {
    let y = BTOP;
    for (const f of col.files) {
      const all = fnsOf(f.path), rows = all.filter(n => linked.has(n.id))
        .sort((a, b) => (changes?.get(b.id) || 0) - (changes?.get(a.id) || 0) || (a.lineno || 0) - (b.lineno || 0));
      const rest = all.length - rows.length, height = BHEAD + rows.length * BROW + (rest ? BROW : 0) + BPAD;
      boxes.push({f, x: c * BCOL, y, height, rows, rest});
      pos.set(f.path, {x: c * BCOL, y, height});
      rows.forEach((n, r) => pos.set(n.id, {x: c * BCOL, y: y + BHEAD + r * BROW + BROW / 2, file: f.path}));
      y += height + BGAP;
    }
    bottom = Math.max(bottom, y);
  });
  const width = (cols.length - 1) * BCOL + BW + 60, height = bottom;

  const svg = svgEl('svg', {class: 'project-map', role: 'group', 'aria-label': '함수 단위 프로젝트 지도'}, box);
  const marker = svgEl('marker', {id: 'map-arrow', viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 6, markerHeight: 6, orient: 'auto'}, svgEl('defs', {}, svg));
  svgEl('path', {d: 'M0 0 L10 5 L0 10 z', class: 'map-arrow'}, marker);
  const view = svgEl('g', {class: 'map-viewport'}, svg);
  cols.forEach((col, c) => {
    svgEl('text', {x: c * BCOL, y: 16, class: 'map-col'}, view, `${col.title} ${col.files.length}`);
    if (col.sub) svgEl('text', {x: c * BCOL, y: 34, class: 'map-sub'}, view, col.sub);
  });
  // A line leaves the right side of its start and enters the left side of its end;
  // when the end is not further right, it bends around the right side instead.
  const curve = (x1, y1, x2, y2) => {
    if (x2 > x1) { const a = x1 + BW, mid = (x2 - a) / 2; return `M ${a} ${y1} C ${a + mid} ${y1}, ${x2 - mid} ${y2}, ${x2} ${y2}`; }
    const right = Math.max(x1, x2) + BW, bend = 24 + Math.min(Math.abs(y1 - y2) * .12, 60);
    return `M ${x1 + BW} ${y1} C ${right + bend} ${y1}, ${right + bend} ${y2}, ${x2 + BW} ${y2}`;
  };
  const lines = svgEl('g', {}, view);
  mapLines = [];
  const seen = new Set();
  for (const e of fnCalls) {
    const p = pos.get(e.source), q = pos.get(e.target), key = e.source + '>' + e.target;
    if (!p || !q || seen.has(key)) continue;
    seen.add(key);
    // Calls inside one file only show up when one of their ends is in focus.
    mapLines.push({a: e.source, b: e.target, node: svgEl('path', {d: curve(p.x, p.y, q.x, q.y),
      class: 'map-edge call fn' + (p.file === q.file ? ' inner' : ''), 'marker-end': 'url(#map-arrow)'}, lines)});
  }
  // Zoomed out: file-level calls and co-change between box headers.
  const head = path => ({x: pos.get(path).x, y: pos.get(path).y + BHEAD / 2});
  for (const e of map.calls) if (shownFiles.has(e.a) && shownFiles.has(e.b)) {
    const p = head(e.a), q = head(e.b);
    mapLines.push({a: 'file:' + e.a, b: 'file:' + e.b, node: svgEl('path', {d: curve(p.x, p.y, q.x, q.y),
      class: 'map-edge call file-level', 'stroke-width': Math.min(1 + Math.log2(e.count) * .55, 4), 'marker-end': 'url(#map-arrow)'}, lines)});
  }
  for (const e of map.cochange) if (shownFiles.has(e.a) && shownFiles.has(e.b)) {
    const p = head(e.a), q = head(e.b);
    mapLines.push({a: 'file:' + e.a, b: 'file:' + e.b, node: svgEl('path', {d: curve(p.x, p.y, q.x, q.y),
      class: 'map-edge co' + (e.hidden ? ' hidden-link' : ''), 'stroke-width': Math.min(1.2 + (e.count - 2) * .6, 4)}, lines)});
  }

  mapItems = new Map();
  const opener = (g, id, label, action) => {
    g.setAttribute('tabindex', 0); g.setAttribute('role', 'button'); g.setAttribute('aria-label', label);
    g.addEventListener('pointerenter', () => mapFocus(id));
    g.addEventListener('pointerleave', () => mapFocus(null));
    g.addEventListener('focus', () => mapFocus(id));
    g.addEventListener('blur', () => mapFocus(null));
    const go = () => { if (!mapZoom.dragged) action(); };
    g.addEventListener('click', go);
    g.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); go(); } });
    mapItems.set(id, g);
  };
  for (const {f, x, y, height: h, rows, rest} of boxes) {
    const group = svgEl('g', {class: 'map-box', transform: `translate(${x} ${y})`}, view);
    svgEl('rect', {class: 'map-box-frame', width: BW, height: h, rx: 7}, group);
    // Header = the file: colour by change count, a click opens the file graph.
    const header = svgEl('g', {class: `map-box-head heat-${heatOf(f.changes)}`}, group);
    svgEl('title', {}, header, `${f.path}\n변경 ${f.changes}회 · 함수 ${f.funcs}개`);
    svgEl('rect', {width: BW, height: BHEAD - 6, rx: 7}, header);
    svgEl('text', {x: 10, y: 16, class: 'map-name'}, header, f.name.length > 24 ? f.name.slice(0, 23) + '…' : f.name);
    svgEl('text', {x: 10, y: 29, class: 'map-meta'}, header, `변경 ${f.changes}회 · 함수 ${f.funcs}`);
    if (f.entry.length) svgEl('text', {x: BW - 9, y: 17, class: 'map-entry', 'text-anchor': 'end'}, header, '★');
    opener(header, 'file:' + f.path, `${f.path}, 변경 ${f.changes}회, 함수 ${f.funcs}개`, () => { if (index.has(f.id)) { showMap(false); choose(f.id); } });
    // Rows = the functions; a click opens that function's call flow.
    rows.forEach((n, r) => {
      const count = changes?.get(n.id) || 0;
      const row = svgEl('g', {class: 'map-fn' + (count ? ' changed' : ''), transform: `translate(0 ${BHEAD + r * BROW})`}, group);
      svgEl('title', {}, row, `${n.name}\n${n.file}:${n.lineno || 1}`);
      svgEl('rect', {x: 4, y: 1, width: BW - 8, height: BROW - 2, rx: 4}, row);
      const label = n.name.split('.').slice(n.type === 'method' ? -2 : -1).join('.');
      svgEl('text', {x: 12, y: BROW / 2 + 4, class: 'map-fn-name'}, row, label.length > 26 ? label.slice(0, 25) + '…' : label);
      if (count) svgEl('text', {x: BW - 10, y: BROW / 2 + 4, class: 'map-fn-badge', 'text-anchor': 'end'}, row, `변경 ${count}`);
      opener(row, n.id, `${n.name}, ${f.path}`, () => { showMap(false); choose(n.id); });
    });
    if (rest) svgEl('text', {x: 12, y: BHEAD + rows.length * BROW + BROW / 2 + 4, class: 'map-sub'}, group, `+ 호출 관계 없는 함수 ${rest}개`);
  }
  // Semantic zoom: below FAR the names are unreadable, so the map switches to its file-level picture.
  mapZoom.onZoom = k => svg.classList.toggle('far', k < FAR);
  setupZoom(mapZoom, svg, view, width, height, controls);

  const legend = el('div', undefined, box); legend.className = 'map-legend';
  el('span', '상자 머리 색 = 파일 변경 횟수', legend);
  HEAT.forEach(([, , label], level) => { el('span', label, legend).className = `map-bin heat-${level}`; });
  el('span', '★ 진입점', legend);
  el('span', '── 함수 호출 (확대 시) · 파일 간 호출 (축소 시)', legend).className = 'map-key call';
  el('span', `- - 함께 변경 (파일 ${mapLimit}개 이하 커밋, 2회 이상)`, legend).className = 'map-key co';
  el('span', '같은 파일 안 호출은 함수에 마우스를 올렸을 때만', legend);
}
// File graph: the functions of one file as nodes, ordered by the calls between them (left calls right),
// with the functions of other files that call in (far left) or are called (far right).
const GW = 210, GH = 46, GCOL = 270, GROW = 60, GTOP = 40, GMAX = 12;
const GKIND = {function: '함수', method: '메서드', class: '클래스'};
function renderFileGraph(file, box) {
  if (fileZoom.file !== file.file) Object.assign(fileZoom, {view: null, file: file.file});
  const members = new Set(data.nodes.filter(n => n.file === file.file && ['function', 'method', 'class'].includes(n.type)).map(n => n.id));
  const inner = calls.filter(e => members.has(e.source) && members.has(e.target) && e.source !== e.target && index.has(e.target));
  const into = calls.filter(e => members.has(e.target) && !members.has(e.source) && index.has(e.source) && index.get(e.source).type !== 'module');
  const out = calls.filter(e => members.has(e.source) && !members.has(e.target) && index.has(e.target));
  const tests = new Set(into.filter(e => isTest(index.get(e.source))).map(e => e.source));
  // External neighbours, most connected first; tests are counted, not drawn.
  const rank = (edges, key) => { const n = new Map(); for (const e of edges) n.set(e[key], (n.get(e[key]) || 0) + 1); return [...n].sort((a, b) => b[1] - a[1]).map(([id]) => id); };
  const callersAll = rank(into.filter(e => !tests.has(e.source)), 'source'), calleesAll = rank(out, 'target');
  const callers = callersAll.slice(0, GMAX), callees = calleesAll.slice(0, GMAX);
  const linked = new Set([...inner.flatMap(e => [e.source, e.target]), ...into.map(e => e.target), ...out.map(e => e.source)]);
  // Layer = breadth-first distance from the file's own starting functions (not called inside the file).
  const calledInside = new Set(inner.map(e => e.target));
  const layer = new Map(), queue = [...members].filter(id => linked.has(id) && !calledInside.has(id));
  queue.forEach(id => layer.set(id, 0));
  for (let i = 0; i < queue.length; i++) for (const e of inner) if (e.source === queue[i] && !layer.has(e.target)) {
    layer.set(e.target, Math.min(layer.get(queue[i]) + 1, 5)); queue.push(e.target);
  }
  for (const id of linked) if (members.has(id) && !layer.has(id)) layer.set(id, 0); // pure cycles
  const layers = [];
  for (const [id, l] of layer) (layers[l] ||= []).push(id);
  // Order each layer by where its callers sit, which keeps lines from crossing too much.
  const row = new Map(), changes = functionChanges();
  layers.forEach((ids, l) => {
    const weight = id => { const ys = inner.filter(e => e.target === id && row.has(e.source)).map(e => row.get(e.source)); return ys.length ? ys.reduce((a, b) => a + b) / ys.length : -1; };
    ids.sort((a, b) => l ? weight(a) - weight(b) : (changes?.get(b) || 0) - (changes?.get(a) || 0) || index.get(a).lineno - index.get(b).lineno);
    ids.forEach((id, r) => row.set(id, r));
  });
  const columns = [callers, ...layers, callees];
  const pos = new Map();
  columns.forEach((ids, c) => ids.forEach((id, r) => { if (!pos.has(id)) pos.set(id, {x: c * GCOL, y: GTOP + r * GROW}); }));
  const width = (columns.length - 1) * GCOL + GW + 40, height = GTOP + Math.max(1, ...columns.map(c => c.length)) * GROW + 30;

  const head = el('div', undefined, box); head.className = 'map-options';
  el('span', `${file.file} · 함수 ${members.size}개 · 파일 안 호출 ${inner.length}개`, head);
  const controls = zoomControls(head);
  el('p', '왼쪽이 이 파일을 부르는 다른 파일의 함수, 가운데가 이 파일의 함수(왼쪽이 오른쪽을 호출), 오른쪽이 이 파일이 부르는 다른 파일의 함수입니다. 함수를 누르면 그 함수의 호출 흐름으로 들어갑니다.', box).className = 'map-lede';
  const svg = svgEl('svg', {class: 'project-map file-graph', role: 'group', 'aria-label': `${file.file}의 함수 흐름`}, box);
  const marker = svgEl('marker', {id: 'file-arrow', viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 6, markerHeight: 6, orient: 'auto'}, svgEl('defs', {}, svg));
  svgEl('path', {d: 'M0 0 L10 5 L0 10 z', class: 'map-arrow'}, marker);
  const view = svgEl('g', {class: 'map-viewport'}, svg);
  const titles = [`이 파일을 부르는 함수 ${callersAll.length}`, ...layers.map((_, l) => l ? `파일 안 ${l}단계` : '이 파일의 시작 함수'), `이 파일이 부르는 함수 ${calleesAll.length}`];
  titles.forEach((t, c) => svgEl('text', {x: c * GCOL, y: 16, class: 'map-col'}, view, t));
  const lines = svgEl('g', {}, view), edges = [], nodes = new Map();
  const path = (p, q) => {
    if (p.x >= q.x) { const x = Math.max(p.x, q.x) + GW, bend = 30 + Math.abs(p.y - q.y) * .15; return `M ${p.x + GW} ${p.y + GH / 2} C ${x + bend} ${p.y + GH / 2}, ${x + bend} ${q.y + GH / 2}, ${q.x + GW} ${q.y + GH / 2}`; }
    const x1 = p.x + GW, x2 = q.x, mid = (x2 - x1) / 2;
    return `M ${x1} ${p.y + GH / 2} C ${x1 + mid} ${p.y + GH / 2}, ${x2 - mid} ${q.y + GH / 2}, ${x2} ${q.y + GH / 2}`;
  };
  const seen = new Set();
  for (const e of [...into, ...inner, ...out]) {
    const key = e.source + '>' + e.target;
    if (seen.has(key) || !pos.has(e.source) || !pos.has(e.target)) continue;
    seen.add(key);
    edges.push({a: e.source, b: e.target, node: svgEl('path', {d: path(pos.get(e.source), pos.get(e.target)),
      class: 'map-edge call' + (e.type === 'calls_implicit' ? ' implicit' : ''), 'marker-end': 'url(#file-arrow)'}, lines)});
  }
  const focus = id => {
    const near = new Set(id ? [id] : []);
    for (const e of edges) { const on = !!id && (e.a === id || e.b === id); if (on) { near.add(e.a); near.add(e.b); } e.node.classList.toggle('near', on); }
    for (const [n, g] of nodes) g.classList.toggle('near', near.has(n));
    svg.classList.toggle('dim', !!id);
  };
  for (const [id, {x, y}] of pos) {
    const n = index.get(id), own = members.has(id), count = changes?.get(id) || 0;
    const g = svgEl('g', {class: 'graph-node' + (own ? '' : ' external') + (count ? ' changed' : ''), transform: `translate(${x} ${y})`,
      tabindex: 0, role: 'button', 'aria-label': `${n.name}, ${n.file}:${n.lineno || 1}`}, view);
    svgEl('title', {}, g, `${n.name}\n${n.file}:${n.lineno || 1}`);
    svgEl('rect', {width: GW, height: GH, rx: 6}, g);
    const label = n.name.split('.').slice(-2).join('.');
    svgEl('text', {x: 10, y: 19, class: 'graph-name'}, g, label.length > 27 ? '…' + label.slice(-26) : label);
    svgEl('text', {x: 10, y: 36, class: 'graph-file'}, g, own ? `${GKIND[n.type]} · ${n.lineno || 1}번째 줄` : `${n.file.split('/').pop()}:${n.lineno || 1}`);
    if (count) svgEl('text', {x: GW - 8, y: 36, class: 'graph-badge', 'text-anchor': 'end'}, g, `변경 ${count}회`);
    g.addEventListener('pointerenter', () => focus(id));
    g.addEventListener('pointerleave', () => focus(null));
    g.addEventListener('focus', () => focus(id));
    g.addEventListener('blur', () => focus(null));
    const enter = () => { if (!fileZoom.dragged) choose(id); };
    g.addEventListener('click', enter);
    g.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); enter(); } });
    nodes.set(id, g);
  }
  const bottom = GTOP + Math.max(callers.length, callees.length) * GROW + 14;
  if (callersAll.length > GMAX) svgEl('text', {x: 0, y: bottom, class: 'map-sub'}, view, `외 ${callersAll.length - GMAX}개`);
  if (calleesAll.length > GMAX) svgEl('text', {x: (columns.length - 1) * GCOL, y: bottom, class: 'map-sub'}, view, `외 ${calleesAll.length - GMAX}개`);
  setupZoom(fileZoom, svg, view, width, height, controls);
  if (tests.size) el('small', `이 파일을 직접 호출하는 테스트 ${tests.size}개는 그림에서 뺐습니다.`, box);
  // Functions without any call found are still listed, so nothing in the file goes missing.
  const loose = [...members].filter(id => !linked.has(id));
  if (loose.length) {
    const more = el('details', undefined, box);
    el('summary', `호출 관계가 확인되지 않은 함수 ${loose.length}개`, more);
    loose.forEach(id => { el('button', index.get(id).name.split('.').slice(-2).join('.'), more, () => choose(id)).className = 'commit'; });
  }
}
$('toggle-map').addEventListener('click', () => { if (data) showMap(!mapMode); });
const gitTabs = ['cochange', 'history', 'insights'];
function updateGitTabs() {
  for (const name of gitTabs) {
    const button = $(name + '-tab');
    button.setAttribute('aria-selected', String(tab === name));
    button.tabIndex = tab === name ? 0 : -1;
  }
  $('history').hidden = tab === 'insights';
  $('git-insights').hidden = tab !== 'insights';
  $('history').setAttribute('aria-labelledby', tab + '-tab');
}
function selectGitTab(name) {
  tab = name;
  updateGitTabs();
  if (selected) history();
  saveLayout();
}
for (const [i, name] of gitTabs.entries()) {
  const button = $(name + '-tab');
  button.addEventListener('click', () => selectGitTab(name));
  button.addEventListener('keydown', event => {
    let next;
    if (event.key === 'ArrowRight') next = (i + 1) % gitTabs.length;
    if (event.key === 'ArrowLeft') next = (i + gitTabs.length - 1) % gitTabs.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = gitTabs.length - 1;
    if (next === undefined) return;
    event.preventDefault(); selectGitTab(gitTabs[next]);
    $(gitTabs[next] + '-tab').focus();
  });
}

// Remember panel widths and visibility for this webview across reloads.
const savedLayout = api.getState?.() || {};
let browserWidth = Number.isFinite(savedLayout.browserWidth) ? savedLayout.browserWidth : 224;
let historyWidth = Number.isFinite(savedLayout.historyWidth) ? savedLayout.historyWidth : 320;
let historyCollapsed = savedLayout.historyCollapsed === true;
if (gitTabs.includes(savedLayout.tab)) tab = savedLayout.tab;
function saveLayout() {
  api.setState?.({browserWidth, historyWidth, historyCollapsed, tab});
}
function applyLayout() {
  const layout = $('layout');
  layout.style.setProperty('--browser-width', `${browserWidth}px`);
  layout.style.setProperty('--history-width', `${historyWidth}px`);
  layout.classList.toggle('history-collapsed', historyCollapsed);
  $('git-sidebar').hidden = historyCollapsed;
  $('history-resize').hidden = historyCollapsed;
  $('toggle-history').textContent = historyCollapsed ? 'Git 패널 열기' : 'Git 패널 접기';
  $('toggle-history').setAttribute('aria-expanded', String(!historyCollapsed));
  for (const [id, width, min, max] of [
    ['browser-resize', browserWidth, 150, 360], ['history-resize', historyWidth, 240, 480]]) {
    $(id).setAttribute('aria-valuenow', String(width));
    $(id).setAttribute('aria-valuemin', String(min));
    $(id).setAttribute('aria-valuemax', String(max));
  }
  requestAnimationFrame(wires);
}
function resizePanel(side, value) {
  if (side === 'browser') browserWidth = Math.max(150, Math.min(360, value));
  else historyWidth = Math.max(240, Math.min(480, value));
  applyLayout(); saveLayout();
}
$('toggle-history').addEventListener('click', () => {
  historyCollapsed = !historyCollapsed; applyLayout(); saveLayout();
});
for (const side of ['browser', 'history']) {
  const handle = $(side + '-resize');
  let drag;
  handle.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    drag = {x: event.clientX, width: side === 'browser' ? browserWidth : historyWidth};
    handle.setPointerCapture(event.pointerId); event.preventDefault();
  });
  handle.addEventListener('pointermove', event => {
    if (drag) resizePanel(side, drag.width + (event.clientX - drag.x) * (side === 'browser' ? 1 : -1));
  });
  for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) {
    handle.addEventListener(type, () => { drag = undefined; });
  }
  handle.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const width = side === 'browser' ? browserWidth : historyWidth;
    const direction = (event.key === 'ArrowRight' ? 1 : -1) * (side === 'browser' ? 1 : -1);
    resizePanel(side, event.key === 'Home' ? 0 : event.key === 'End' ? 10000 : width + direction * 20);
  });
}
applyLayout(); updateGitTabs();
window.addEventListener('message', ({data:message}) => {
  if (message.type === 'gitValidationStatus') $('git-validation-status').textContent = message.text;
  if (message.type === 'gitValidation') { gitValidation = message.data; changeCounts = undefined;
    $('git-validation-status').textContent = gitValidation.available ? 'Git 분석 완료' : 'Git 이력 없음';
    renderGitValidation(); if (index.has(selected)) flow(); if (mapMode) renderMap(); return; }
  if (message.type === 'status') $('status').textContent = message.text;
  if (message.type !== 'data') return;
  data = message.data; changeCounts = undefined;
  index = new Map(data.nodes.map(n => [n.id,n]));
  calls = data.edges.filter(e => ['calls','calls_override','instantiates','calls_implicit'].includes(e.type));
  const s = data.summary;
  const counts = data.status_summary?.statuses || {};
  const cutoffs = data.flow?.recursion_or_budget_cutoffs || 0;
  $('status').textContent = `${s.files} Python 파일 · 내부 호출 ${counts.RESOLVED_INTERNAL || 0} · 외부·내장 ${counts.KNOWN_NON_INTERNAL || 0} · 미확정 ${counts.UNKNOWN || 0} · 저장된 소스의 정적 후보${data.warnings.length ? ' · 파싱 제외: '+data.warnings.join('; ') : ''}${cutoffs ? ` · 재귀·계산 한도에서 보수적 처리 ${cutoffs}회` : ''}`;
  const initial = data.nodes.find(n => n.file === message.initialFile && ['function','method'].includes(n.type)) || data.nodes.find(n => ['function','method'].includes(n.type)) || data.nodes[0];
  trail = trail.filter(id => index.has(id));
    if (initial) { choose(index.has(selected) ? selected : initial.id, false);
    showMap(mapMode); }
  else {
    selected = undefined; tree();
    for (const id of ['focus','flow','evidence','history','history-file']) $(id).replaceChildren();
    el('p', '분석할 Python 코드가 없습니다.', $('flow'));
  }
});
api.postMessage({type:'ready'});

window.addEventListener('resize', () => requestAnimationFrame(wires));

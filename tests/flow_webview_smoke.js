/* A small DOM harness for behavior checks; it does not validate browser layout. */
class MockElement {
  constructor(tag) { this.tag=tag; this.children=[]; this.events={}; this.attrs={}; this.dataset={}; this.value=''; this.textContent=''; this.style={setProperty(key,value){this[key]=value;}}; this.classList={toggle(){}}; }
  append(node) { this.children.push(node); }
  replaceChildren(...nodes) { this.children=nodes; this.textContent=''; }
  addEventListener(type, callback) { this.events[type]=callback; }
  setAttribute(key,value) { this.attrs[key]=value; }
}
const elements=new Map(), listeners={}, messages=[];
const document={
  getElementById(id) { if(!elements.has(id)) elements.set(id,new MockElement('div')); return elements.get(id); },
  createElement(tag) { return new MockElement(tag); },
  createElementNS(ns, tag) { return new MockElement(tag); },
  querySelector() { return null; }
};
const window={addEventListener(type,callback){listeners[type]=callback;}};
function requestAnimationFrame() {} // Layout is verified separately in a real browser.
function acquireVsCodeApi() { return {postMessage(message){messages.push(message);}}; }
function assert(value,message) { if(!value)throw new Error(message); }
function text(node) { return node.textContent+' '+node.children.map(text).join(' '); }
function find(node,predicate) { if(predicate(node))return node; for(const child of node.children){const match=find(child,predicate);if(match)return match;} }
load('vscode-extension/media/map.js');
const payload=JSON.parse(readFile(arguments[0]));
const target=payload.nodes.find(n=>n.name.endsWith('.target') || n.name==='target');
const caller=payload.nodes.find(n=>n.name.endsWith('.caller') || n.name==='caller');
payload.entry_points=[{id:caller.id,kind:'main_call',confidence:'certain'}];
listeners.message({data:{type:'data',data:payload,initialFile:target.file}});
assert(text(elements.get('project-map')).includes('직접 실행 코드'),'start candidate explains its source');
assert(entryReason({kind:'public_api',confidence:'certain'}).why.includes('__all__'),'explicit export reason');
assert(entryReason({kind:'public_api',confidence:'inferred'}).why.includes('__init__.py'),'inferred export reason');
assert(entryReason({kind:'console_script',confidence:'certain'}).label==='설치된 명령의 연결 대상','console-script reason');
assert(activeRoute[0]===caller.id&&activeRoute.includes(target.id),'intro route follows actual directed calls');
assert(new Set(representativePath(caller.id)).size===representativePath(caller.id).length,'intro route has no repeated nodes');
assert(!find(elements.get('project-map'),n=>n.tag==='g'&&String(n.attrs.class).startsWith('map-fn')),'file boxes start collapsed');
assert(text(elements.get('project-map')).includes('어떤 함수부터 읽어볼까요?'),'project introduction before map');
assert(find(elements.get('project-map'),n=>n.tag==='details'&&n.className==='project-intro').open,'introduction opens on first visit');
assert(elements.get('git-sidebar').hidden,'Git sidebar starts collapsed on map');
const expand=find(elements.get('project-map'),n=>n.tag==='g'&&n.attrs['aria-label']===target.file+' 함수 펼치기');
assert(expand,'file has accessible expand action'); expand.events.click();
assert(find(elements.get('project-map'),n=>n.tag==='g'&&String(n.attrs.class).startsWith('map-fn')),'expanded file draws function nodes');
listeners.message({data:{type:'gitValidation',data:{available:false}}});
assert(expandedFiles.has(target.file),'Git update preserves expanded files');
const mapFile=find(elements.get('project-map'),n=>n.tag==='g'&&String(n.attrs.class).startsWith('map-box-head'));
assert(mapFile,'project map draws file boxes'); mapFile.events.click();
assert(selected==='file:'+target.file,'map opens the file view');
assert(text(elements.get('breadcrumbs')).includes(target.file),'file breadcrumb shows full path');
assert(find(elements.get('flow'),n=>n.tag==='g'&&String(n.attrs.class).startsWith('graph-node')),'file view draws the function graph');
choose(target.id);
assert(!introExpanded,'choosing a function collapses the introduction');
const activeSymbol=find(elements.get('tree'),n=>n.tag==='button'&&n.attrs['aria-current']==='true');
assert(activeSymbol&&activeSymbol.attrs['data-node-id']===target.id&&!text(activeSymbol).includes('선택됨'),'sidebar marks selected function without badge');
assert(text(elements.get('focus')).includes(target.name),'full canonical name is available');
assert(text(elements.get('focus')).includes('선언된 시그니처'),'selected function exposes its signature');
assert(text(elements.get('breadcrumbs')).includes(target.name),'function breadcrumb shows location');
const breadcrumbFile=find(elements.get('breadcrumbs'),n=>n.tag==='button'&&n.textContent===target.file);
assert(breadcrumbFile,'function breadcrumb links to owning file');
const selectedFilter=find(elements.get('breadcrumbs'),n=>n.tag==='input'); selectedFilter.checked=true; selectedFilter.events.change();
assert(onlySelection&&selectedCallEdges().every(e=>selectionScope().has(e.source)&&selectionScope().has(e.target)),'selected flow excludes unrelated endpoints');
const resetFilter=find(elements.get('breadcrumbs'),n=>n.tag==='input');resetFilter.checked=false;resetFilter.events.change();
assert(!onlySelection,'selected flow filter can be cleared');
assert(layers(target.id,true,1)[0].includes(caller.id),'directed caller expansion');
assert(isTest({file:'tests/test_x.py'})&&isTest({file:'pkg/a_test.py'})&&!isTest({file:'main.py'})&&!isTest({file:'src/contest.py'}),'test file detection');
assert(text(elements.get('flow')).includes('코드 ↗'),'source actions');
elements.get('more').events.click();
assert(text(elements.get('depth')).includes('2단계'),'depth control');
choose(caller.id);
assert(text(elements.get('evidence')).includes('미확정'),'unknown call visible');
assert(text(elements.get('evidence')).includes('넘기는 값')||text(elements.get('evidence')).includes('전달값'),'call arguments paired with parameters');
assert(text(elements.get('evidence')).includes('조건부 콜백 후보'),'callbacks distinguished');
assert(!text(elements.get('status')).includes('반복 한도 도달'),'no fabricated convergence warning');
const link=find(elements.get('evidence'),n=>n.tag==='button'&&n.textContent.includes('unknown'));
link.events.click();
assert(messages.at(-1).type==='open'&&messages.at(-1).line===5,'unknown callsite source action');
elements.get('back').events.click();
assert(text(elements.get('focus')).includes('target'),'back restores focus');
calls.push({source:target.id,target:target.id,type:'calls'});
assert(!layers(target.id,true,3).flat().includes(target.id),'cycle terminates');
elements.get('search').value='<script>';elements.get('search').events.input();
assert(!elements.get('tree').children.length,'search filters tree');
// Git tabs remain exclusive, including before detailed analysis is available.
elements.get('insights-tab').events.click();
assert(elements.get('history').hidden && !elements.get('git-insights').hidden,'insights replaces history');
assert(elements.get('insights-tab').attrs['aria-selected']==='true','selected tab semantics');
elements.get('history-tab').events.click();
assert(!elements.get('history').hidden && elements.get('git-insights').hidden,'history replaces insights');
elements.get('toggle-history').events.click();
assert(elements.get('git-sidebar').hidden,'Git panel collapses');
assert(elements.get('toggle-history').attrs['aria-expanded']==='false','collapsed toggle semantics');
elements.get('toggle-history').events.click();
assert(!elements.get('git-sidebar').hidden,'Git panel reopens');
elements.get('collapse-history').events.click();
assert(elements.get('git-sidebar').hidden,'Git panel collapses from its own heading');
elements.get('toggle-history').events.click();
assert(!elements.get('git-sidebar').hidden&&tab==='history','reopening preserves the selected Git tab');
const key=key=>({key,preventDefault(){}});
elements.get('browser-resize').events.keydown(key('ArrowRight'));
assert(elements.get('layout').style['--browser-width']==='244px','left panel keyboard resize');
elements.get('history-resize').events.keydown(key('ArrowLeft'));
assert(elements.get('layout').style['--history-width']==='340px','right panel keyboard resize');
elements.get('browser-resize').events.keydown(key('Home'));
assert(elements.get('browser-resize').attrs['aria-valuenow']==='150','minimum panel width');
elements.get('history-resize').events.keydown(key('End'));
assert(elements.get('history-resize').attrs['aria-valuenow']==='480','maximum panel width');
choose(target.id);
listeners.message({data:{type:'gitValidation',data:{available:true,analyzed_commits:2,authors:[{}],files:{[target.file]:{
  commits:2,authors:[{name:'alice',count:1},{name:'bob',count:1}],types:{feature:2},functions:[],cochanges:[],
  events:[{author:'alice',sha:'aaaaaaaa',type:'feature',functions:[target.name]},
          {author:'bob',sha:'bbbbbbbb',type:'feature',functions:[caller.name]}]
}}}}});
assert(text(elements.get('flow')).includes('변경 1회'),'flow cards show function change counts');
const authorSelect=find(elements.get('git-validation-panel'),n=>n.tag==='select');
authorSelect.value='alice'; authorSelect.events.change();
assert(text(elements.get('git-validation-panel')).includes('선택 범위: 1개 커밋'),'author filters event count');
assert(text(elements.get('git-validation-panel')).includes('기능 추가 1'),'commit types follow author filter');
const hotspot=find(elements.get('git-validation-panel'),n=>n.tag==='button'&&text(n).includes(target.name));
assert(hotspot,'hotspot links to current function'); hotspot.events.click();
assert(messages.at(-1).type==='open'&&messages.at(-1).id===target.id,'hotspot opens source');
data.working_changes={available:true,basis:'HEAD',warnings:[],files:[{file:target.file,functions:[{
  name:target.name,kind:'modified',facts:['본문 변경'],node_id:target.id,callers:[caller.id]
}]}]}; renderWorkingChanges();
const impactCaller=find(elements.get('working-changes'),n=>n.tag==='button'&&n.textContent.startsWith('호출자:'));
assert(impactCaller,'changed function lists direct caller'); impactCaller.events.click();
assert(messages.at(-1).id===caller.id,'impact caller opens source');
listeners.message({data:{type:'data',data:{...payload,nodes:[],edges:[]}}});
assert(text(elements.get('flow')).includes('분석할 Python 코드가 없습니다'),'empty clears view');
print('Flow webview behavior OK');

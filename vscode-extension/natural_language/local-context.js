'use strict';
const {readSource,hash}=require('./source');
const {runtimeEvidence, staticEvidence}=require('./evidence');
async function buildLocalContext(root,data,id,traceFile='.knitcode/trace.json') {
  const target=data.nodes.find(n=>n.id===id);
  if (!target || !['function','method','file','module','class'].includes(target.type)) throw new Error('파일·클래스·함수를 선택하세요.');
  const source=await readSource(root,target.file), digest=hash(source);
  if (!data.source_hashes?.[target.file] || data.source_hashes[target.file]!==digest)
    throw new Error('저장된 소스와 분석 결과가 다릅니다. 저장 후 다시 분석하세요.');
  const lines=source.split('\n'), isFunction=['function','method'].includes(target.type);
  const endOf=n=>n.navigation_metadata?.end_lineno;
  const scope=data.nodes.filter(n=>['function','method'].includes(n.type) && n.file===target.file &&
    (target.type!=='class' || (n.lineno>=target.lineno && endOf(n)<=endOf(target))));
  const candidates=isFunction ? [target] : scope.sort((a,b)=>a.lineno-b.lineno || a.id.localeCompare(b.id));
  // Summarize up to three outermost functions, not arbitrary prefixes of a whole module.
  const picked=[];
  for (const n of candidates) {
    if (picked.some(p=>p.lineno<=n.lineno && endOf(p)>=endOf(n))) continue;
    picked.push(n); if(picked.length===3)break;
  }
  const limitations=[
    '모델은 선택된 함수 본문만 요약합니다. 프로젝트 전체의 목적이나 실제 실행 순서를 추론하지 않습니다.',
    '짧은 코드 표현에는 용어 규칙을 적용하고, 나머지 문장은 설치된 Argos 모델로 번역합니다.',
    '영어 요약과 한국어 변환은 검증된 코드 사실이 아닙니다. 근거 코드와 대조하세요.'
  ], sources=[];
  for (const n of picked) {
    const end=endOf(n);
    if (!Number.isInteger(n.lineno) || !Number.isInteger(end) || n.lineno<1 || end<n.lineno || end>lines.length) {
      limitations.push(`${n.name}: 함수 범위를 확인할 수 없어 제외했습니다.`);continue;
    }
    const text=lines.slice(n.lineno-1,end).join('\n');
    if(text.length>60000){limitations.push(`${n.name}: 본문이 60,000자를 넘어 제외했습니다.`);continue;}
    sources.push({id:`S${sources.length+1}`,nodeId:n.id,name:n.name,file:n.file,start:n.lineno,end,text});
  }
  if (!isFunction) limitations.push(`파일·클래스의 전체 요약이 아닙니다. 분석된 함수 ${scope.length}개 중 앞쪽 최대 3개를 개별 요약합니다.`);
  const members = data.nodes.filter(n => n.file === target.file && (
    isFunction ? n.id === id : target.type === 'class' ?
      n.id === id || (n.lineno >= target.lineno && endOf(n) <= endOf(target)) : true));
  const memberIds = new Set(members.map(n => n.id));
  const edges=(data.edges||[]).filter(e=>['calls','calls_override','calls_implicit','instantiates'].includes(e.type));
  const callers=new Set(edges.filter(e=>memberIds.has(e.target)&&!memberIds.has(e.source)).map(e=>e.source));
  const callees=new Set(edges.filter(e=>memberIds.has(e.source)&&!memberIds.has(e.target)).map(e=>e.target));
  const names = new Map(data.nodes.map(node => [node.id, node.name]));
  function describe(ids) {
    const examples = Array.from(ids).slice(0, 3).map(id => names.get(id) || id);
    return examples.length ? `${ids.size}개 (${examples.join(', ')})` : '0개';
  }
  const structure = [
    `${target.name || target.file} · ${target.file}:${target.lineno}`,
    `정적 호출 그래프에서 선택 범위 밖의 호출자 후보는 ${describe(callers)}, 호출 대상 후보는 ${describe(callees)}입니다.`
  ];
  structure.push(...staticEvidence(data,target));
  const runtime = isFunction ? await runtimeEvidence(root, traceFile, target, digest, data, callees) : '실행 관측값을 보려면 함수 하나를 선택하세요.';
  const payload={runtime,target:{id,name:target.name,file:target.file,type:target.type},sources,structure,limitations};
  return {payload,snapshots:{[target.file]:digest},fingerprint:hash(JSON.stringify(payload))};
}
module.exports={buildLocalContext};

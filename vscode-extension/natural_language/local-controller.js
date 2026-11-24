'use strict';
const {buildLocalContext}=require('./local-context');
const {checkSnapshot,hash}=require('./source');
const provider=require('./local-provider');
function createLocalController({vscode,context,root,folder,post,openSource,getData,isBusy},deps={}) {
  const build=deps.build || buildLocalContext,check=deps.check || checkSnapshot,generate=deps.generate || provider.generate;
  let epoch=0,pending=null,preparing=false,disposed=false;
  const records=new Map(),cache=new Map();
  const send=m=>{if(!disposed)post({type:'localState',...m});};
  const put=(map,key,value)=>{map.delete(key);map.set(key,value);while(map.size>20)map.delete(map.keys().next().value);};
  const model=()=>vscode.workspace.getConfiguration('knitcodeStatic',folder.uri).get('localModel','base');
  const preference=()=>vscode.workspace.getConfiguration('knitcodeStatic',folder.uri).get('localDevice','auto');
  function executionKey() {
    return preference()+':'+provider.execution(provider.runtimePath(context),preference()).backend;
  }
  function reset(){epoch++;pending?.controller.abort();pending=null;preparing=false;records.clear();cache.clear();}
  async function handle(message) {
    if(disposed || !vscode.workspace.isTrusted)return;
    if(message.type==='roleLocalSetup'){await vscode.commands.executeCommand('knitcodeStatic.setupLocalModel');return;}
    if(message.type==='roleLocalCancel'){
      const id=pending?.id || preparing;
      if(id && message.id===id){epoch++;pending?.controller.abort();pending=null;preparing=false;send({id,state:'error',text:'로컬 요청을 취소했습니다.'});}return;
    }
    if(isBusy() || !getData()?.nodes.some(n=>n.id===message.id)){
      send({id:message.id,state:'error',text:'분석이 완료된 뒤 코드를 다시 선택하세요.'});
      return;
    }
    const id=message.id;let attempt=epoch;
    try {
      if(message.type==='roleLocalPrepare'){
        if(pending || preparing){send({id,state:'error',text:'다른 로컬 요약이 진행 중입니다.'});return;}
        const selected=model();if(!['small','base'].includes(selected))throw new Error('로컬 모델 설정을 확인하세요.');
        attempt=++epoch;preparing=id;send({id,state:'loading',text:'선택한 함수 본문을 준비하는 중…'});
        const bundle=await build(root,getData(),id,vscode.workspace.getConfiguration('knitcodeStatic',folder.uri).get('localTraceFile') || '.knitcode/trace.json');
        if(disposed || attempt!==epoch)return;
        preparing=false;
        const token=hash(provider.VERSION+executionKey()+selected+bundle.fingerprint),record={id,token,model:selected,bundle};
        put(records,token,record);
        const common={id,token,model:selected,sources:bundle.payload.sources,structure:bundle.payload.structure,runtime:bundle.payload.runtime,notices:bundle.payload.limitations};
        const result=cache.get(token);
        if(result && !message.force){send({...common,state:'complete',cached:true,result});return;}
        send({...common,state:'preview'});return;
      }
      const record=records.get(message.token);
      if(!record || record.id!==id)throw new Error('요약 준비가 만료되었습니다. 다시 준비하세요.');
      if(message.type==='roleLocalOpen'){
        const source=record.bundle.payload.sources.find(s=>s.id===message.source);if(!source)return;
        await check(root,record.bundle);await openSource(source.file,source.start,source.end);return;
      }
      if(message.type!=='roleLocalGenerate')return;
      if(pending || preparing)throw new Error('다른 로컬 요청이 진행 중입니다. 완료 후 다시 시도하세요.');
      if(record.used)throw new Error('분석 근거를 다시 읽은 뒤 요약을 생성하세요.');
      if(record.model!==model())throw new Error('모델 설정이 변경되었습니다. 다시 준비하세요.');
      if(!record.bundle.payload.sources.length)throw new Error('요약할 함수 본문이 없습니다. 함수를 직접 선택하세요.');
      record.used=true;attempt=++epoch;
      const task={id,controller:new AbortController()};pending=task;
      send({id,state:'loading',text:'함수 요약을 생성하고 있습니다…'});
      try {
        await check(root,record.bundle);
        if(disposed || epoch!==attempt)return;
        const result=await generate({context,model:record.model,bundle:record.bundle,preference:preference(),signal:task.controller.signal});
        if(disposed || epoch!==attempt)return;
        await check(root,record.bundle);
        if(disposed || epoch!==attempt)return;
        put(cache,record.token,result);
        send({id,state:'complete',token:record.token,model:record.model,result,cached:false,
          sources:record.bundle.payload.sources,structure:record.bundle.payload.structure,runtime:record.bundle.payload.runtime,notices:record.bundle.payload.limitations});
      } finally{if(pending===task)pending=null;}
    } catch(e){if(!disposed && epoch===attempt){if(preparing===id)preparing=false;send({id,state:'error',text:e.message});}}
  }
  return {handle,reset,dispose(){disposed=true;reset();}};
}
module.exports={createLocalController};

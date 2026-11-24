(function(global){
  const states=new Map();let current,container,send,installation;
  function node(tag,text,parent,action){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;parent.append(n);if(action)n.addEventListener('click',action);return n;}
  function showSummary(box, state, id, post) {
    for (const item of state.result.summaries) {
      const card=node('section', undefined, box);
      card.className='function-summary';
      node('small', item.name, card);
      const headline=node('p', item.korean || item.english || '생성된 요약이 없습니다.', card);
      headline.className='summary-headline';
      headline.setAttribute('lang', item.korean ? 'ko' : 'en');
      if (item.korean) {
        const original=node('p', item.english, card);
        original.className='summary-original';
        original.setAttribute('lang', 'en');
        original.setAttribute('aria-label', 'CodeT5 영어 원문');
      }
      if (item.codeLike) node('small', '모델이 코드 형태로 응답했습니다.', card);
      if (item.truncated) node('small', '긴 함수의 앞부분만 요약했습니다.', card);
      if (item.outputTruncated) node('small', '출력 한도에 도달한 미완성 문장입니다.', card);
      const source=state.sources.find(s=>s.id===item.source);
      if (source) node('button', '근거 코드 보기', card,
        ()=>post({type:'roleLocalOpen',id,token:state.token,source:source.id}));
    }
  }
  function render(box,id,post){
    current=id;container=box;send=post;box.replaceChildren();box.className='role-explanation local-explanation';
    const state=states.get(id)||{};
    node('h3',state.state==='complete' ? '함수 역할 요약' : '선택한 코드 해설',box);
    if(state.state==='complete') showSummary(box,state,id,post);
    else node('p',`선택한 코드 · ${id}`,box);
    const actions=node('div',undefined,box);actions.className='explanation-actions';
    const prepare=force=>{states.set(id,{state:'loading',text:'함수 본문 준비 중…'});render(box,id,post);post({type:'roleLocalPrepare',id,force});};
    if(!state.state){
      node('p','분석 근거를 준비하고 있습니다.',box);
      return;
    }
    if(state.state!=='loading'){
      if(state.state==='error')node('button','분석 근거 다시 읽기',actions,()=>prepare(false));
      if(state.state==='complete')node('button','새 요약 준비',actions,()=>prepare(true));
      if (installation && (!installation.codeReady || !installation.koReady)) {
        if (installation.installing) node('small','모델 설치 중…',actions);
        else node('button',installation.codeReady ? '한국어 번역 모델 추가' : '요약·번역 모델 설치',
          actions,()=>post({type:'roleLocalSetup'}));
      }
    } else node('button','로컬 요청 취소',actions,()=>post({type:'roleLocalCancel',id}));
    if(state.text)node('p',state.text,box).setAttribute('role','status');
    if(state.structure){
      node('p',`CodeT5 ${state.model} · 함수 ${state.sources.length}개 · CPU 연산 2스레드`,box).className='role-meta';
      const structure=node('div',undefined,box);node('strong','정적 분석에서 확인한 위치와 연결',structure);
      for(const line of state.structure)node('p',line,structure);
      if (state.runtime) {
        node('strong','동적 분석 · 실행 기록',structure);
        node('p',state.runtime,structure);
      }
    }
    if(state.state==='preview'){
      const details=node('details',undefined,box);node('summary','모델이 읽을 함수 본문 확인',details);
      for(const source of state.sources){node('strong',`${source.name} · ${source.file}:${source.start}–${source.end}`,details);node('pre',source.text,details);}
      node('p','함수당 입력 최대 512토큰·출력 최대 64토큰. 주석과 docstring을 제외한 본문을 요약하며, 입력이 길면 일부만 사용했다고 표시합니다.',box);
      if(state.sources.length && installation?.codeReady !== false)node('button','CPU로 요약 생성',box,()=>{
        states.set(id,{...state,state:'loading',text:'CPU에서 모델을 불러오는 중…'});render(box,id,post);post({type:'roleLocalGenerate',id,token:state.token});
      });
      else if(!state.sources.length) node('p','이 선택에는 요약 가능한 함수가 없습니다. 함수를 직접 선택하세요.',box);
    }
    if(state.state==='complete') node('small',state.cached ? '이전에 생성한 요약' :
      `CodeT5 생성 완료${state.result.seconds===null?'':` · 모델 로딩 포함 ${state.result.seconds}초`}`,box);
    if(state.notices){const details=node('details',undefined,box);node('summary','요약 범위와 한계',details);for(const line of state.notices)node('p',line,details);}

  }
  global.KnitCodeLocalView={render,setInstallation(next){
    installation=next;
    if(current && container)render(container,current,send);
  },hasState(id){return states.has(id);},detach(){current=null;container=null;send=null;},clear(){states.clear();this.detach();},receive(message){
    if(message.type!=='localState')return false;
    const previous=states.get(message.id);
    const next=previous?.structure && ['loading','error'].includes(message.state) ? {...previous,...message} : message;
    states.delete(message.id);states.set(message.id,next);while(states.size>20)states.delete(states.keys().next().value);
    if(message.id===current && container)render(container,current,send);return true;
  }};
})(globalThis);

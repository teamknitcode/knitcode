'use strict';
const {spawn} = require('node:child_process');
const {createInterface} = require('node:readline');
const path = require('node:path');

let current;

function closeWorker() {
  current?.stop(new Error('로컬 모델 작업이 종료됐습니다.'));
}

function openWorker(python, runtime, model, backend, key) {
  closeWorker();
  const child = spawn(python, ['-I','-B',path.join(__dirname,'local_model.py'),
    '--worker','--runtime',runtime,'--model',model,'--backend',backend], {
    cwd:runtime, windowsHide:true, shell:false, stdio:['pipe','pipe','pipe'],
    env:{...process.env,PYTHONIOENCODING:'utf-8',HF_HUB_DISABLE_TELEMETRY:'1'}
  });
  const lines = createInterface({input:child.stdout});
  let pending, idle, stderr='';
  const worker = {key, request, stop};
  current = worker;
  child.stderr.setEncoding('utf8');
  child.stderr.on('data', chunk => { stderr=(stderr+chunk).slice(-1600); });
  child.on('error', stop);
  child.stdin.on('error', stop);
  child.on('close', () => stop(new Error(stderr || '로컬 모델 프로세스가 종료됐습니다.')));
  lines.on('line', line => {
    if (!pending) return;
    try {
      const reply = JSON.parse(line);
      if (reply.error) throw new Error(reply.error);
      pending.resolve(reply);
      pending.cleanup();
      pending=undefined;
      idle=setTimeout(closeIfCurrent, 300000);
      idle.unref();
    } catch (error) { stop(error); }
  });
  function closeIfCurrent() { if (current===worker) closeWorker(); }
  function stop(error) {
    if (current===worker) current=undefined;
    clearTimeout(idle);
    if (pending) { pending.cleanup(); pending.reject(error); pending=undefined; }
    lines.close();
    if (!child.killed && child.exitCode===null) child.kill();
  }
  function request(sources, signal) {
    if (pending) return Promise.reject(new Error('다른 모델 요청이 진행 중입니다.'));
    clearTimeout(idle);
    return new Promise((resolve,reject) => {
      const abort=()=>stop(new Error('요약 생성을 취소했습니다.'));
      const timer=setTimeout(()=>stop(new Error('모델 응답 시간이 초과됐습니다.')),180000);
      pending={resolve,reject,cleanup(){clearTimeout(timer);signal?.removeEventListener('abort',abort);}};
      signal?.addEventListener('abort',abort,{once:true});
      if (signal?.aborted) { abort(); return; }
      child.stdin.write(JSON.stringify({sources})+'\n','utf8',error=>{if(error)stop(error);});
    });
  }
  return worker;
}

function summarize(python, runtime, model, backend, sources, signal) {
  const key=JSON.stringify([python,runtime,model,backend]);
  const worker=current?.key===key ? current : openWorker(python,runtime,model,backend,key);
  return worker.request(sources,signal);
}
module.exports={summarize,closeWorker};

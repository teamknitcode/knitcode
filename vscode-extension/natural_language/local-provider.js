'use strict';
const path=require('path'),fs=require('fs'),{spawn,execFile}=require('child_process');
const {translate,VERSION:KO_VERSION}=require('./local-ko');
const VERSION='local-codet5-2:'+KO_VERSION;
const {EventEmitter} = require('node:events');
const installs = new EventEmitter();
const translator = 'argos-en-ko-1.1';
let running=false;
let installing=false;
const runtimePath=context=>path.join(context.globalStorageUri.fsPath,'codet5-cpu');
const pythonPath=runtime=>path.join(runtime,'venv',process.platform==='win32'?'Scripts':'bin',process.platform==='win32'?'python.exe':'python');
function installation(context, model) {
  const runtime = runtimePath(context);
  const exists = (dir, files) => files.every(name => fs.existsSync(path.join(dir, name)));
  function readMarker(dir) {
    try { return JSON.parse(fs.readFileSync(path.join(dir, 'ready.json'), 'utf8')); }
    catch { return {}; }
  }
  const codeDir = path.join(runtime, 'models', model);
  const koDir = path.join(runtime, 'models', translator);
  const marker = readMarker(codeDir);
  const python = fs.existsSync(pythonPath(runtime));
  const weight = model === 'base' ? 'pytorch_model.bin' : 'model.safetensors';
  const codeReady = python && marker.weights === weight &&
    exists(codeDir, [weight, 'config.json', 'merges.txt', 'vocab.json']);
  const koReady = python && readMarker(koDir).model === translator &&
    exists(koDir, ['model/model.bin', 'model/shared_vocabulary.txt', 'sentencepiece.model']);
  return {codeReady, koReady, installing};
}

async function translateSummaries(result, {python, runtime, signal, runner}) {
  const items = result.summaries.filter(item => !item.korean && item.english &&
    !item.codeLike && !item.outputTruncated);
  if (!items.length) return;
  try {
    const worker = path.join(__dirname, 'translate_ko.py');
    const response = await runner(python, ['-I', '-B', worker, '--runtime', runtime], {
      input: JSON.stringify(items.map(item => item.english)), cwd: runtime, signal
    });
    if (response.code !== 0) return;
    const lines = JSON.parse(response.stdout);
    if (!Array.isArray(lines) || lines.length !== items.length) return;
    lines.forEach((line, i) => {
      if (typeof line === 'string' && line.length <= 3000 && /[가-힣]/.test(line)) {
        Object.assign(items[i], {korean: line, status: 'translated', rule: 'argos-en-ko'});
      }
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    // The original English summary remains available if the translator fails.
  }
}
function stop(child) {
  if (!child?.pid) return;
  if(process.platform==='win32') execFile('taskkill',['/PID',String(child.pid),'/T','/F'],{windowsHide:true},()=>{});
  else {try{process.kill(-child.pid,'SIGKILL');}catch{child.kill('SIGKILL');}}
}
function runProcess(executable,args,{input='',signal,timeout=180000,onOutput,cwd}={},spawnProcess=spawn) {
  return new Promise((resolve,reject)=>{
    if(signal?.aborted){reject(new Error('요청을 취소했습니다.'));return;}
    let child,stdout='',stderr='',failure,done=false;
    const finish=(error,result)=>{if(done)return;done=true;clearTimeout(timer);signal?.removeEventListener('abort',abort);error?reject(error):resolve(result);};
    const abort=()=>{failure=new Error('요청을 취소했습니다.');stop(child);};
    const timer=setTimeout(()=>{failure=new Error('로컬 작업 시간 제한을 초과했습니다. 작은 함수를 선택하거나 설치 로그를 확인하세요.');stop(child);},timeout);
    try {child=spawnProcess(executable,args,{cwd,windowsHide:true,detached:process.platform!=='win32',shell:false,
      env:{...process.env,PYTHONUTF8:'1',PYTHONIOENCODING:'utf-8',CUDA_VISIBLE_DEVICES:'',HF_HUB_DISABLE_TELEMETRY:'1'},stdio:['pipe','pipe','pipe']});}
    catch(e){finish(e);return;}
    signal?.addEventListener('abort',abort,{once:true});
    if(signal?.aborted)abort();
    child.on('error',e=>finish(new Error(`로컬 Python을 실행하지 못했습니다 (${e.code || '오류'}). 로컬 모델 설치와 Python 경로를 확인하세요.`)));
    child.stdout.setEncoding('utf8');child.stderr.setEncoding('utf8');
    child.stdout.on('data',chunk=>{onOutput?.(chunk);stdout+=chunk;if(stdout.length>200000){if(onOutput)stdout=stdout.slice(-100000);else{failure=new Error('로컬 출력 한도를 초과했습니다.');stop(child);}}});
    child.stderr.on('data',chunk=>{onOutput?.(chunk);stderr=(stderr+chunk).slice(-5000);});
    child.stdin.on('error',()=>{});
    child.on('close',code=>finish(failure,{code,stdout,stderr}));
    child.stdin.end(input);
  });
}
function parseResult(raw,bundle) {
  if(raw.device!=='cpu' || !Array.isArray(raw.summaries) || raw.summaries.length!==bundle.payload.sources.length)
    throw new Error('로컬 모델 응답 형식이 올바르지 않습니다.');
  const ids=new Set();
  const summaries=raw.summaries.map(item=>{
    const source=bundle.payload.sources.find(s=>s.id===item.id);
    if(!source || ids.has(item.id) || typeof item.english!=='string' || item.english.length>3000 ||
       typeof item.truncated!=='boolean' || typeof item.output_truncated!=='boolean' ||
       !Number.isInteger(item.input_tokens) || !Number.isInteger(item.used_tokens) || item.used_tokens<1 || item.used_tokens>512)
      throw new Error('로컬 요약의 출처 또는 범위를 확인할 수 없습니다.');
    ids.add(item.id);
    const converted=translate(item.english);
    const codeLike=/^(?:print\s*\(|def\s+\w+\s*\(|class\s+\w+[:(]|[A-Za-z_]\w*\s*=(?!=))/.test(item.english.trim());
    // A cut-off output can accidentally match a short valid pattern: keep it untranslated.
    if(item.output_truncated || codeLike){converted.korean=null;converted.status='unsupported';converted.rule=null;}
    return {...converted,source:source.id,name:source.name,inputTokens:item.input_tokens,
      usedTokens:item.used_tokens,truncated:item.truncated,outputTruncated:item.output_truncated,codeLike};
  });
  return {model:raw.model,seconds:Number.isFinite(raw.seconds)?raw.seconds:null,device:'cpu',summaries};
}
async function generate({context,model,bundle,signal},runner=runProcess) {
  if(!['small','base'].includes(model))throw new Error('지원하지 않는 로컬 모델입니다.');
  if(running)throw new Error('다른 로컬 작업이 진행 중입니다. 완료 후 다시 시도하세요.');
  const runtime=runtimePath(context),python=pythonPath(runtime);
  if(!fs.existsSync(python) || !fs.existsSync(path.join(runtime,'models',model,'ready.json')))
    throw new Error('로컬 모델이 아직 없습니다. 「로컬 모델 설치」를 먼저 실행하세요.');
  running=true;
  try {
    const response=await runner(python,['-I','-B',path.join(__dirname,'local_model.py'),'--runtime',runtime,'--model',model],
      {input:JSON.stringify({sources:bundle.payload.sources.map(s=>({id:s.id,text:s.text}))}),signal,cwd:runtime});
    let raw;try{raw=JSON.parse(response.stdout);}catch{throw new Error('로컬 모델 응답을 읽지 못했습니다. 설치를 다시 실행하세요.');}
    if(response.code!==0 || raw.error)throw new Error(`로컬 요약 실패: ${String(raw.error || 'Python 실행 오류').slice(0,1200)}`);
    const result = parseResult(raw,bundle);
    if (installation(context, model).koReady) await translateSummaries(result, {python,runtime,signal,runner});
    return result;
  } finally {running=false;}
}
async function setup(vscode,context) {
  if(!vscode.workspace.isTrusted)return;
  if(running){vscode.window.showInformationMessage('다른 로컬 작업이 진행 중입니다.');return;}
  const config=vscode.workspace.getConfiguration('knitcodeStatic');
  const model=config.get('localModel','base');
  if(!['small','base'].includes(model))throw new Error('로컬 모델 설정을 확인하세요.');
  const custom=config.get('localSetupPython','');
  const installedPython = pythonPath(runtimePath(context));
  const reusePython = !custom && fs.existsSync(installedPython);
  const python = custom || (reusePython ? installedPython : process.platform==='win32' ? 'py' : 'python3');
  const prefix = !custom && !reusePython && process.platform==='win32' ? ['-3.11'] : [];
  const output=vscode.window.createOutputChannel('KnitCode Local Model');output.show(true);
  const runtime=runtimePath(context);
  fs.mkdirSync(runtime,{recursive:true});
  output.appendLine(`CodeT5 ${model} 및 Argos 영어→한국어 번역 모델을 준비합니다. 기존 설치를 재사용합니다.`);
  running=true; installing=true; installs.emit('change');
  try {
    await vscode.window.withProgress({location:vscode.ProgressLocation.Notification,title:`KnitCode · 로컬 모델 설치 (${model})`,cancellable:true},async(_progress,token)=>{
      const controller=new AbortController();const sub=token.onCancellationRequested(()=>controller.abort());
      if(token.isCancellationRequested)controller.abort();
      try {
        const r=await runProcess(python,[...prefix,'-I','-B',path.join(__dirname,'local_model.py'),'--setup','--runtime',runtime,'--model',model],
          {signal:controller.signal,timeout:1800000,onOutput:text=>output.append(text),cwd:runtime});
        if(r.code!==0)throw new Error('로컬 모델 설치 실패. 출력 로그를 확인하세요. Python 3.11~3.13 경로는 knitcodeStatic.localSetupPython에서 지정할 수 있습니다.');
      } finally{sub.dispose();}
    });
    vscode.window.showInformationMessage('요약·번역 모델 설치 완료. A 모드에서 CPU로 요약 생성을 누르세요.');
  } catch(e){vscode.window.showErrorMessage(e.message);}
  finally{running=false;installing=false;installs.emit('change');}
}
module.exports={installation,installs,VERSION,generate,parseResult,setup,runtimePath,pythonPath,runProcess};

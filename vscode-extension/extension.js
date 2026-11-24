const vscode = require('vscode');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const os = require('os');
const { execFile } = require('child_process');

function activate(context) {
  context.subscriptions.push(vscode.commands.registerCommand('knitcodeStatic.setupLocalModel',
    () => require('./natural_language/local-provider').setup(vscode, context)));
  context.subscriptions.push(vscode.commands.registerCommand('knitcodeStatic.open', async () => {
    if (!vscode.workspace.isTrusted) return;
    if ((vscode.workspace.workspaceFolders || []).some(f => f.uri.scheme !== 'file')) {
      vscode.window.showErrorMessage('knitcode는 로컬 파일 시스템 프로젝트가 필요합니다.'); return;
    }
    const folders = vscode.workspace.workspaceFolders || [];
    const folder = folders.length === 1 ? folders[0] : await vscode.window.showWorkspaceFolderPick();
    if (!folder) { vscode.window.showInformationMessage('먼저 분석할 프로젝트 폴더를 열어주세요.'); return; }
    const root = folder.uri.fsPath;
    const activeFile = vscode.window.activeTextEditor?.document.uri;
    const initialFile = activeFile?.scheme === 'file' ? path.relative(root, activeFile.fsPath).split(path.sep).join('/') : undefined;
    const media = vscode.Uri.joinPath(context.extensionUri, 'media');
    const panel = vscode.window.createWebviewPanel('knitcodeStatic.map', `knitcode · ${folder.name}`, vscode.ViewColumn.Beside,
      { enableScripts: true, localResourceRoots: [media], retainContextWhenHidden: true });
    const nonce = crypto.randomBytes(16).toString('hex');
    const resource = name => panel.webview.asWebviewUri(vscode.Uri.joinPath(media, name));
    panel.webview.html = `<!doctype html><html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${panel.webview.cspSource}; script-src 'nonce-${nonce}';"><link rel="stylesheet" href="${resource('map.css')}"><link rel="stylesheet" href="${resource('bmode.css')}"><link rel="stylesheet" href="${resource('natural_language/a-view.css')}"></head><body>
      <header><div><b>knitcode</b></div><div class="header-actions"><button id="mode-a" aria-pressed="false">A · 정밀 분석</button><button id="mode-b" aria-pressed="true">B · 구조 이해</button><button id="toggle-map" aria-pressed="true">함수 화면 보기</button><button id="toggle-history" aria-controls="git-sidebar" aria-expanded="true">Git 패널 접기</button><button id="refresh">재분석</button></div></header>
      <p id="status" role="status">분석 준비 중…</p>
      <main id="layout"><aside class="browser" id="code-browser"><span class="panel-label">코드 탐색</span><input id="search" placeholder="파일·함수 검색" aria-label="파일·함수 검색"><div id="tree"></div></aside>
      <div id="browser-resize" class="panel-resize" role="separator" tabindex="0" aria-orientation="vertical" aria-label="파일 탐색 너비" aria-controls="code-browser"></div><section class="workspace"><section id="a-explanation" aria-label="선택한 코드 해설"></section><nav id="breadcrumbs" aria-label="현재 탐색 위치"></nav><section id="project-map" aria-label="프로젝트 지도" hidden></section><div id="focus"></div><nav id="flow-controls"><div><button id="back">← 이전 선택</button><button id="less">− 단계</button><span id="depth"></span><button id="more">+ 단계</button></div><small>호출자를 왼쪽으로 · 호출 대상을 오른쪽으로</small></nav><div id="flow" aria-label="함수 중심 호출 흐름"></div><section id="evidence"></section></section>
      <div id="history-resize" class="panel-resize" role="separator" tabindex="0" aria-orientation="vertical" aria-label="Git 패널 너비" aria-controls="git-sidebar"></div>
      <aside class="history" id="git-sidebar"><div class="git-heading"><h2>파일의 변경 맥락</h2><button id="collapse-history" aria-label="Git 패널 접기" aria-controls="git-sidebar">접기 ›</button></div><p id="history-file"></p><div class="git-tabs" role="tablist" aria-label="Git 보기"><button id="cochange-tab" role="tab" aria-controls="history" aria-selected="true">함께 변경</button><button id="history-tab" role="tab" aria-controls="history" aria-selected="false" tabindex="-1">변경 이력</button><button id="insights-tab" role="tab" aria-controls="git-insights" aria-selected="false" tabindex="-1">심층 분석</button></div><div id="history" role="tabpanel" aria-labelledby="cochange-tab"></div><section id="git-insights" class="git-validation-section" role="tabpanel" aria-labelledby="insights-tab" hidden><section id="working-changes"></section><p>작성자별 변경 · 함수 핫스팟 · 공동 변경</p><button id="git-validation-run">Git 상세 분석 다시 실행</button> <button id="git-validation-report">정적분석 + Git 통합 보고서 ↗</button><p id="git-validation-status" role="status">분석 대기 중</p><div id="git-validation-panel"></div></section></aside></main>
      <section id="b-mode" hidden aria-label="KnitCode B 모드 구조 이해">
        <div class="b-hero"><div><span class="b-eyebrow">MODE B · STRUCTURE EXPLORER</span><h1>프로젝트 구조 한눈에 보기</h1><p id="b-overview">분석 결과를 불러오는 중입니다.</p></div><div class="b-kpis"><div><strong id="b-stat-files">—</strong><small>파일</small></div><div><strong id="b-stat-groups">—</strong><small>구성 영역</small></div><div><strong id="b-stat-links">—</strong><small>영역 간 호출 관계</small></div></div></div>
        <div class="b-top">
          <section class="b-map-panel" aria-label="아키텍처 지도"><div class="b-panel-heading"><div><h2>전체 아키텍처 · 기능별 그룹</h2><p>함수·클래스 단위 역할 후보와 근거가 있는 정적 호출 연결선</p></div><div class="b-toolbar"><label>보기 방식 <select id="b-view-style" aria-label="아키텍처 분류 기준"><option value="roles">역할 계층</option><option value="folders">실제 폴더</option></select></label><label><input id="b-show-tests" type="checkbox"> 테스트 포함</label><button id="b-reset">전체 보기</button></div></div><div id="b-map-scroll" class="b-map-scroll"><div id="b-canvas" class="b-canvas"><svg id="b-links" role="img" aria-label="구성 영역 사이의 호출 관계"></svg><div id="b-group-grid" class="b-group-grid"></div></div></div><p class="b-legend" id="b-legend">영역을 누르면 구성 파일과 함수를 볼 수 있습니다.</p></section>
          <aside class="b-guide" aria-label="프로젝트 탐색 질문"><div class="b-panel-heading"><div><h2>무엇이 궁금한가요?</h2><p>질문을 누르면 실제 분석 결과로 안내합니다.</p></div></div><div class="b-questions"><button data-b-question="entry">어디서부터 읽을까?</button><button data-b-question="service">핵심 처리 영역은?</button><button data-b-question="data">데이터 저장·조회는 어디서?</button><button data-b-question="external">외부 API 연동은?</button><button data-b-question="connected">어떤 영역이 많이 연결될까?</button><button data-b-question="files">파일이 많은 영역은?</button><button data-b-question="changes">최근 변경된 영역은?</button></div><p class="b-disclaimer">기능 이름은 자동 분류 후보이며 AST 근거와 이름 추정을 구분합니다. 연결선은 정적 호출 후보로 실행 순서·데이터 흐름을 증명하지 않습니다.</p></aside>
        </div>
        <section class="b-answer-panel" aria-label="질문 답변 및 영역 설명"><div class="b-answer-heading"><span>QUESTION &amp; AREA INSIGHT</span><h2 id="b-answer-heading">선택한 영역 요약</h2></div><div id="b-question-answer" class="b-question-answer" role="status">관심 있는 질문이나 지도 속 영역을 선택해보세요.</div></section>
        <section class="b-detail" aria-label="선택한 영역 상세 보기"><div class="b-panel-heading"><div><h2 id="b-selection-title">영역을 선택하세요</h2><p id="b-selection-subtitle">패키지 → 파일 → 함수 순서로 살펴볼 수 있습니다.</p></div><div class="b-detail-actions"><button id="b-open-a" disabled>선택 함수 A 모드에서 보기</button><button id="b-open-code" disabled>소스코드 열기 ↗</button></div></div><div id="b-detail-content" class="b-detail-content"><p class="b-placeholder">지도에서 구성 요소를 선택하면 해당 위치의 파일과 함수가 이곳에 표시됩니다.</p></div></section>
      </section>
      <script nonce="${nonce}" src="${resource('natural_language/local-view.js')}"></script>
      <script nonce="${nonce}" src="${resource('natural_language/a-view.js')}"></script>
      <script nonce="${nonce}" src="${resource('map.js')}"></script><script nonce="${nonce}" src="${resource('bmode.js')}"></script></body></html>`;
    let child, gitChild, reportChild, disposed = false, data, busy = false;
    panel.onDidDispose(() => { disposed = true; if (child) child.kill(); if (gitChild) gitChild.kill(); if (reportChild) reportChild.kill(); });
    const resetLocal = require('./natural_language/host').attachLocalAnalysis({
      vscode, context, folder, root, panel, getData: () => data, isBusy: () => busy, safeFile
    });
    async function analyze() {
      if (busy || disposed) return;
      busy = true;
      resetLocal();
      panel.webview.postMessage({type: 'status', text: 'Python 코드와 Git 이력 분석 중…'});
      const config = vscode.workspace.getConfiguration('knitcodeStatic', folder.uri);
      const bundled = path.join(context.extensionPath, 'vendor');
      const engine = fs.existsSync(path.join(bundled, 'vscode_export.py')) ? bundled : path.dirname(context.extensionPath);
      const python = config.get('pythonPath') || (process.platform === 'win32' ? 'python' : 'python3');
      child = execFile(python, ['-I', '-B', path.join(engine, 'vscode_export.py'), root, '--days', String(config.get('historyDays')), '--limit', String(config.get('commitLimit'))],
        {cwd: engine, env: {...process.env, PYTHONDONTWRITEBYTECODE: '1'}, maxBuffer: 64 * 1024 * 1024, timeout: 180000},
        (error, stdout, stderr) => {
          busy = false; child = undefined;
          if (disposed) return;
          if (error) { panel.webview.postMessage({type: 'status', text: `분석 실패: ${stderr || error.message} · 설정의 knitcodeStatic.pythonPath를 확인하세요.`}); return; }
          try { data = JSON.parse(stdout); panel.webview.postMessage({type: 'data', data, initialFile});
            if (config.get('gitValidationAutoRun', true)) analyzeGitValidation(); }
          catch (e) { panel.webview.postMessage({type: 'status', text: `결과를 읽지 못했습니다: ${e.message}`}); }
        });
    }

    // KnitCode Git Validation UI PATCH v1: extra analysis never blocks static flow.
    async function analyzeGitValidation() {
      if (disposed || gitChild) return;
      const config = vscode.workspace.getConfiguration('knitcodeStatic', folder.uri);
      const bundled = path.join(context.extensionPath, 'vendor');
      const engine = fs.existsSync(path.join(bundled, 'vscode_export.py')) ? bundled : path.dirname(context.extensionPath);
      const script = path.join(engine, 'git_validation', 'vscode_json_cli.py');
      if (!fs.existsSync(script)) {
        panel.webview.postMessage({type:'gitValidationStatus', text:'Git Validation 파일이 확장에 포함되지 않았습니다. 최신 VSIX를 다시 패키징하세요.'});
        return;
      }
      const python = config.get('pythonPath') || (process.platform === 'win32' ? 'python' : 'python3');
      panel.webview.postMessage({type:'gitValidationStatus', text:'Git 변경 이력과 함수 핫스팟 분석 중…'});
      gitChild = execFile(python, ['-I', '-B', script, root, '--commits', String(config.get('gitValidationCommitLimit', 50))],
        {cwd: engine, env: {...process.env, PYTHONDONTWRITEBYTECODE: '1'}, maxBuffer: 16 * 1024 * 1024, timeout: 180000},
        (error, stdout, stderr) => {
          gitChild = undefined;
          if (disposed) return;
          if (error) { panel.webview.postMessage({type:'gitValidationStatus', text:`Git 분석 실패: ${stderr || error.message}`}); return; }
          try { panel.webview.postMessage({type:'gitValidation', data:JSON.parse(stdout)}); }
          catch (e) { panel.webview.postMessage({type:'gitValidationStatus', text:`Git 분석 결과 파싱 실패: ${e.message}`}); }
        });
    }
    async function openGitValidationReport() {
      if (disposed || reportChild) return;
      const config = vscode.workspace.getConfiguration('knitcodeStatic', folder.uri);
      const bundled = path.join(context.extensionPath, 'vendor');
      const engine = fs.existsSync(path.join(bundled, 'vscode_export.py')) ? bundled : path.dirname(context.extensionPath);
      const script = path.join(engine, 'git_validation', 'integrated_cli.py');
      if (!fs.existsSync(script)) {
        vscode.window.showErrorMessage('Git Validation 통합 CLI가 없습니다. 전체 git_validation/ 파일과 패키징 상태를 확인하세요.'); return;
      }
      const python = config.get('pythonPath') || (process.platform === 'win32' ? 'python' : 'python3');
      const out = fs.mkdtempSync(path.join(os.tmpdir(), 'knitcode-git-report-'));
      panel.webview.postMessage({type:'gitValidationStatus', text:'동일 커밋의 정적분석 + Git 통합 보고서 생성 중…'});
      reportChild = execFile(python, ['-I', '-B', script, root, '--commits', String(config.get('gitValidationCommitLimit', 50)), '--output', out],
        {cwd: engine, env: {...process.env, PYTHONDONTWRITEBYTECODE: '1', GIT_TERMINAL_PROMPT: '0'}, maxBuffer: 16 * 1024 * 1024, timeout: 600000},
        async (error, stdout, stderr) => {
          reportChild = undefined;
          if (disposed) return;
          if (error) { panel.webview.postMessage({type:'gitValidationStatus', text:`통합 보고서 생성 실패: ${stderr || error.message}`}); return; }
          const report = path.join(out, 'index.html');
          if (!fs.existsSync(report)) { panel.webview.postMessage({type:'gitValidationStatus', text:'통합 보고서 파일을 찾을 수 없습니다.'}); return; }
          panel.webview.postMessage({type:'gitValidationStatus', text:'통합 보고서 생성 완료 · 브라우저에서 열기'});
          try { await vscode.env.openExternal(vscode.Uri.file(report)); }
          catch (e) { vscode.window.showErrorMessage(`보고서 열기 실패: ${e.message} · 위치: ${report}`); }
        });
    }
    async function safeFile(relative) {
      if (typeof relative !== 'string' || path.isAbsolute(relative)) throw new Error('잘못된 파일 경로');
      const target = await fs.promises.realpath(path.resolve(root, relative));
      const base = await fs.promises.realpath(root);
      const rel = path.relative(base, target);
      if (rel.startsWith('..' + path.sep) || rel === '..' || path.isAbsolute(rel)) throw new Error('프로젝트 밖의 파일');
      return vscode.Uri.file(target);
    }
    panel.webview.onDidReceiveMessage(async message => {
      try {
        if (!message || typeof message !== 'object') return;
        if (message.type === 'ready' || message.type === 'refresh') await analyze();
        if (message.type === 'gitValidationRun') await analyzeGitValidation();
        if (message.type === 'gitValidationReport') await openGitValidationReport();
        if (message.type === 'open' && data) {
          const node = data.nodes.find(n => n.id === message.id);
          if (!node) return;
          const line = Number.isInteger(message.line) && (data.edges.some(e => e.source === node.id && e.lineno === message.line) || data.call_statuses.some(c => c.file === node.file && (node.type === 'file' || c.caller_id === node.id) && c.line === message.line)) ? message.line : node.lineno || 1;
          const document = await vscode.workspace.openTextDocument(await safeFile(node.file));
          const position = new vscode.Position(Math.min(Math.max(0, line - 1), document.lineCount - 1), 0);
          await vscode.window.showTextDocument(document, {viewColumn: vscode.ViewColumn.One, selection: new vscode.Range(position, position)});
        }
        if (message.type === 'commit' && data) {
          const commit = data.history.commits.find(c => c.sha === message.sha);
          if (!commit) return;
          execFile('git', ['-C', root, 'show', '--format=fuller', '--stat', '--patch', commit.sha, '--', '.'], {maxBuffer: 16 * 1024 * 1024, timeout: 30000}, async (error, text) => {
            if (error) { vscode.window.showErrorMessage(error.message); return; }
            const doc = await vscode.workspace.openTextDocument({language: 'diff', content: text});
            await vscode.window.showTextDocument(doc, vscode.ViewColumn.One);
          });
        }
      } catch (error) { vscode.window.showErrorMessage(`knitcode: ${error.message}`); }
    });
  }));
}
module.exports = {activate};

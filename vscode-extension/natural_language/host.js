'use strict';
const {createLocalController} = require('./local-controller');

const {installation, installs} = require('./local-provider');

function attachLocalAnalysis({vscode, context, folder, root, panel, getData, isBusy, safeFile}) {
  const controller = createLocalController({
    vscode, context, folder, root, getData, isBusy,
    post: message => panel.webview.postMessage(message),
    async openSource(file, start, end) {
      const doc = await vscode.workspace.openTextDocument(await safeFile(file));
      const range = new vscode.Range(doc.lineAt(start - 1).range.start, doc.lineAt(end - 1).range.end);
      await vscode.window.showTextDocument(doc, {viewColumn: vscode.ViewColumn.One, selection: range});
    }
  });
  function publishInstallation() {
    const config = vscode.workspace.getConfiguration('knitcodeStatic', folder.uri);
    const model = config.get('localModel', 'base');
    panel.webview.postMessage({type: 'localInstallation', ...installation(context, model)});
  }
  installs.on('change', publishInstallation);
  const listener = vscode.workspace.onDidChangeConfiguration(event => {
    if (event.affectsConfiguration('knitcodeStatic.localModel', folder.uri)) publishInstallation();
  });
  panel.onDidDispose(() => {
    installs.off('change', publishInstallation);
    listener.dispose();
    controller.dispose();
  });
  panel.webview.onDidReceiveMessage(m => {
    if (m?.type === 'ready' || m?.type === 'roleLocalPrepare') publishInstallation();
    if (m && ['roleLocalSetup', 'roleLocalPrepare', 'roleLocalGenerate', 'roleLocalCancel', 'roleLocalOpen'].includes(m.type))
      return controller.handle(m);
  });
  return () => {
    controller.reset();
    panel.webview.postMessage({type: 'localReset'});
  };
}
module.exports = {attachLocalAnalysis};

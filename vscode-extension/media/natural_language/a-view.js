'use strict';
(() => {
  const content = document.getElementById('a-explanation');
  const view = window.KnitCodeLocalView;
  let selected, visible = false, active;

  function send(message) {
    if (message.type === 'roleLocalPrepare' || message.type === 'roleLocalGenerate') {
      if (active) {
        view.receive({type: 'localState', id: message.id, state: 'error',
          text: '다른 요청이 완료된 뒤 다시 시도하세요.'});
        return;
      }
      active = message.id;
    }
    api.postMessage(message);
  }

  function update() {
    if (!visible || !selected) {
      view.detach();
      content.replaceChildren();
      content.textContent = '코드 탐색에서 파일이나 함수를 선택하면 분석 근거가 표시됩니다.';
      return;
    }
    view.render(content, selected, send);
    if (!active && !view.hasState(selected)) send({type: 'roleLocalPrepare', id: selected});
  }

  window.KnitAExplanation = {
    select(id) {
      if (id === selected) return;
      selected = id;
      update();
    },
    setVisible(next) {
      visible = next;
      update();
    }
  };

  window.addEventListener('message', ({data}) => {
    if (data.type === 'localReset') {
      active = selected = undefined;
      view.clear();
      update();
    } else if (data.type === 'localInstallation') {
      view.setInstallation(data);
    } else if (data.type === 'localState') {
      view.receive(data);
      if (active === data.id && data.state !== 'loading') {
        active = undefined;
        if (visible && selected !== data.id) update();
      }
    }
  });
})();

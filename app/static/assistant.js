(() => {
  const el = {
    root: null,
    panel: null,
    prompt: {},
    chat: {},
  };

  function h(tag, attrs = {}, ...children) {
    const n = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (k === 'class') n.className = v; else if (k === 'style') n.style.cssText = v; else if (k.startsWith('on')) n.addEventListener(k.slice(2), v); else n.setAttribute(k, v);
    });
    children.flat().forEach(c => n.append(c instanceof Node ? c : document.createTextNode(c)));
    return n;
  }

  function togglePanel(show) {
    el.panel.style.display = show ? 'block' : 'none';
  }

  async function fetchJSON(url, options) {
    const res = await fetch(url, Object.assign({ headers: { 'Content-Type': 'application/json' } }, options));
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  }

  // Prompt helper
  async function loadPresets() {
    try {
      const data = await fetchJSON('/prompt/presets');
      const ll = el.prompt.quality;
      ll.innerHTML = '';
      (data.quality || []).forEach(q => ll.append(h('span', { class: 'asst-chip', onclick: () => addToPrompt(q) }, q)));
      el.prompt.negDefault.textContent = data.negative_default || '';
      const styleSel = el.prompt.style;
      styleSel.innerHTML = '<option value="">樣式（自動偵測）</option>';
      Object.entries(data.styles || {}).forEach(([k, v]) => {
        styleSel.append(h('option', { value: k }, v.name || k));
      });
    } catch (e) {
      // ignore
    }
  }

  function addToPrompt(t) {
    el.prompt.input.value = (el.prompt.input.value ? el.prompt.input.value + ', ' : '') + t;
  }

  async function expandPrompt() {
    const payload = {
      prompt: el.prompt.input.value,
      style: el.prompt.style.value,
      include_quality: el.prompt.includeQ.checked ? '1' : '0',
    };
    try {
      const data = await fetchJSON('/prompt/expand', { method: 'POST', body: JSON.stringify(payload) });
      el.prompt.output.value = data.prompt || '';
      el.prompt.negOutput.value = data.negative_suggestion || '';
    } catch (e) {
      el.prompt.output.value = '無法展開提示詞：' + e.message;
    }
  }

  // Chat (LLM navigator)
  const chatState = { messages: [] };

  function pushMsg(role, content) {
    chatState.messages.push({ role, content });
    const div = h('div', { class: 'asst-msg ' + (role === 'user' ? 'me' : 'bot') }, content);
    el.chat.list.append(div);
    el.chat.list.scrollTop = el.chat.list.scrollHeight;
  }

  async function sendChat() {
    const text = el.chat.input.value.trim();
    if (!text) return;
    el.chat.input.value = '';
    pushMsg('user', text);
    try {
      const payload = { messages: chatState.messages, path: location.pathname };
      const data = await fetchJSON('/assistant/chat', { method: 'POST', body: JSON.stringify(payload) });
      pushMsg('assistant', data.reply || '(無回覆)');
    } catch (e) {
      pushMsg('assistant', '無法連線助理：' + e.message);
    }
  }

  function buildUI() {
    const root = h('div', { class: 'asst-root' });
    const btn = h('button', { class: 'asst-btn', title: '提示詞助手 / 導覽員', onclick: () => togglePanel(el.panel.style.display !== 'block') }, '🤖');

    const panel = h('div', { class: 'asst-panel' });
    const header = h('div', { class: 'asst-header' },
      h('div', {}, '助理'),
      h('div', { class: 'asst-tabs' },
        el.tabPrompt = h('button', { class: 'asst-tab active', onclick: () => switchTab('prompt') }, '提示詞'),
        el.tabChat = h('button', { class: 'asst-tab', onclick: () => switchTab('chat') }, '導覽員'),
      )
    );

    const body = h('div', { class: 'asst-body' });

    // Prompt section
    const secPrompt = h('div', { class: 'asst-section active' });
    el.prompt.input = h('textarea', { class: 'asst-textarea', placeholder: '輸入你的提示詞（正面）' });
    el.prompt.style = h('select', { class: 'asst-input' });
    el.prompt.includeQ = h('input', { type: 'checkbox', checked: true });
    el.prompt.quality = h('div', { class: 'asst-list' });
    el.prompt.output = h('textarea', { class: 'asst-textarea', placeholder: '展開後的提示詞', readOnly: true });
    el.prompt.negOutput = h('textarea', { class: 'asst-textarea', placeholder: '建議的負面詞', readOnly: true });
    el.prompt.negDefault = h('div', { class: 'asst-hint' }, '');
    const row1 = h('div', { class: 'asst-row' }, el.prompt.style, h('label', {}, el.prompt.includeQ, ' 加入品質詞'));
    const row2 = h('div', { class: 'asst-row' }, h('button', { class: 'asst-btn-sm', onclick: expandPrompt }, '展開'));
    secPrompt.append(
      h('div', { class: 'asst-hint' }, '提示詞助手：匯入品質詞 / 樣式並清理格式'),
      el.prompt.input,
      row1,
      h('div', { class: 'asst-hint' }, '常用品質：'),
      el.prompt.quality,
      row2,
      el.prompt.output,
      el.prompt.negOutput,
      h('div', { class: 'asst-hint' }, '預設負面詞：'),
      el.prompt.negDefault,
    );

    // Chat section
    const secChat = h('div', { class: 'asst-section' });
    el.chat.list = h('div', { class: 'asst-chat' });
    el.chat.input = h('input', { class: 'asst-input', placeholder: '問我：功能在哪裡 / 怎麼做…', onkeydown: (e) => { if (e.key === 'Enter') sendChat(); } });
    const rowSend = h('div', { class: 'asst-row' }, el.chat.input, h('button', { class: 'asst-btn-sm', onclick: sendChat }, '送出'));
    secChat.append(
      h('div', { class: 'asst-hint' }, '導覽員：協助你在本站操作、導引頁面'),
      el.chat.list,
      rowSend,
    );

    body.append(secPrompt, secChat);
    panel.append(header, body);

    root.append(btn, panel);
    el.root = root; el.panel = panel;
    document.body.append(root);

    loadPresets();
  }

  function switchTab(which) {
    const secs = el.panel.querySelectorAll('.asst-section');
    secs.forEach((s, i) => s.classList.toggle('active', (which === 'prompt' && i === 0) || (which === 'chat' && i === 1)));
    el.tabPrompt.classList.toggle('active', which === 'prompt');
    el.tabChat.classList.toggle('active', which === 'chat');
  }

  function ensureAssets() {
    // If CSS not present, inject
    const have = Array.from(document.styleSheets).some(ss => (ss.href || '').includes('/static/assistant.css'));
    if (!have) {
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = (window.FLASK_STATIC_BASE || '/static') + '/assistant.css';
      document.head.appendChild(link);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { ensureAssets(); buildUI(); });
  } else {
    ensureAssets(); buildUI();
  }
})();


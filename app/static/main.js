// Polished interactions for all pages
document.addEventListener('DOMContentLoaded', () => {
  function showError(el, payload) {
    const text = typeof payload === 'string' ? payload : JSON.stringify(payload, null, 2);
    el.innerHTML = '❌ 發生錯誤\n<pre style="white-space:pre-wrap">' + text + '</pre>';
  }

  function showOk(el, text) {
    el.textContent = '✅ ' + (text || '完成');
  }

  function renderImageCard(container, titleText, url) {
    container.innerHTML = '';
    const card = document.createElement('div');
    card.className = 'card result';
    const title = document.createElement('h2');
    title.textContent = titleText || '最新結果';
    const img = document.createElement('img');
    img.src = url;
    card.appendChild(title);
    card.appendChild(img);
    container.appendChild(card);
  }

  async function submitWithBusy(form, msgEl, url, onSuccess) {
    const btn = form.querySelector('button[type="submit"], .btn');
    if (btn) btn.disabled = true;
    msgEl.textContent = '⏳ 處理中...';
    try {
      const res = await fetch(url, { method: 'POST', body: new FormData(form) });
      const j = await res.json();
      if (res.ok) {
        showOk(msgEl, j.message);
        if (onSuccess) onSuccess(j);
      } else {
        showError(msgEl, j);
      }
    } catch (err) {
      showError(msgEl, String(err));
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  // Try-on Step 1 (首頁)
  const form1 = document.getElementById('form1');
  const p1msg = document.getElementById('p1msg');
  let personUploaded = false;
  if (form1 && p1msg) {
    form1.addEventListener('submit', async (e) => {
      e.preventDefault();
      await submitWithBusy(form1, p1msg, '/upload1', () => { personUploaded = true; });
    });
  }

  // Try-on Step 2 (首頁)
  const form2 = document.getElementById('form2');
  const p2msg = document.getElementById('p2msg');
  const resultDiv = document.getElementById('result');
  if (form2 && p2msg && resultDiv) {
    form2.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!personUploaded) { alert('請先上傳人像'); return; }
      await submitWithBusy(form2, p2msg, '/upload2', (j) => {
        renderImageCard(resultDiv, '最新結果', j.download);
      });
    });
  }

  // Text -> Image
  const t2iForm = document.getElementById('t2iForm');
  const t2iMsg = document.getElementById('t2iMsg');
  const t2iResult = document.getElementById('t2iResult');
  if (t2iForm && t2iMsg && t2iResult) {
    t2iForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      await submitWithBusy(t2iForm, t2iMsg, '/text2image', (j) => {
        renderImageCard(t2iResult, '最新結果', j.download);
      });
    });
  }

  // Image -> Image
  const i2iForm = document.getElementById('i2iForm');
  const i2iMsg = document.getElementById('i2iMsg');
  const i2iResult = document.getElementById('i2iResult');
  if (i2iForm && i2iMsg && i2iResult) {
    i2iForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      await submitWithBusy(i2iForm, i2iMsg, '/img2img', (j) => {
        renderImageCard(i2iResult, '最新結果', j.download);
      });
    });
  }

  // Inpaint
  const inpaintForm = document.getElementById('inpaintForm');
  const inpaintMsg = document.getElementById('inpaintMsg');
  const inpaintResult = document.getElementById('inpaintResult');
  if (inpaintForm && inpaintMsg && inpaintResult) {
    inpaintForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      await submitWithBusy(inpaintForm, inpaintMsg, '/inpaint', (j) => {
        renderImageCard(inpaintResult, '最新結果', j.download);
      });
    });
  }
});


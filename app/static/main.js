// Enhanced interactions and UX helpers
document.addEventListener('DOMContentLoaded', () => {
  // Toasts
  const toastBox = (() => { const c = document.createElement('div'); c.className = 'toast-container'; document.body.appendChild(c); return c; })();
  function toast(msg, type = '') { const t = document.createElement('div'); t.className = 'toast' + (type ? ' ' + type : ''); t.textContent = msg; toastBox.appendChild(t); setTimeout(() => t.remove(), 3500); }

  // Theme toggle (light/dark via CSS variables)
  try {
    const root = document.documentElement;
    const saved = localStorage.getItem('theme');
    if (saved) root.setAttribute('data-theme', saved);
    const btn = document.getElementById('themeToggle');
    if (btn) {
      btn.addEventListener('click', () => {
        const current = root.getAttribute('data-theme') || 'dark';
        const next = current === 'light' ? 'dark' : 'light';
        root.setAttribute('data-theme', next);
        localStorage.setItem('theme', next);
      });
    }
  } catch {}

  function showError(el, payload) {
    const text = typeof payload === 'string' ? payload : JSON.stringify(payload, null, 2);
    el.innerHTML = '❌ 發生錯誤\n<pre style="white-space:pre-wrap">' + text + '</pre>';
  }
  function showOk(el, text) { el.textContent = '✅ ' + (text || '完成'); }

  function renderImageCard(container, titleText, url) {
    container.innerHTML = '';
    const card = document.createElement('div'); card.className = 'card result';
    const title = document.createElement('h2'); title.textContent = titleText || '最新結果';
    const img = document.createElement('img'); img.src = url; img.style.cursor = 'zoom-in';
    card.appendChild(title); card.appendChild(img);

    const actions = document.createElement('div'); actions.className = 'row';
    const btnCopy = document.createElement('button'); btnCopy.className = 'btn ghost'; btnCopy.textContent = '複製連結';
    btnCopy.addEventListener('click', async () => { try { await navigator.clipboard.writeText(url); toast('已複製下載連結', 'success'); } catch { toast('無法複製', 'error'); } });
    const btnDl = document.createElement('a'); btnDl.className = 'btn secondary'; btnDl.textContent = '下載圖片'; btnDl.href = url; btnDl.download = '';
    actions.appendChild(btnCopy); actions.appendChild(btnDl); card.appendChild(actions);

    const modal = document.getElementById('imgModal');
    if (modal) { img.addEventListener('click', () => { const mimg = modal.querySelector('img'); mimg.src = url; modal.style.display = 'flex'; }); modal.addEventListener('click', () => { modal.style.display = 'none'; }); }

    container.appendChild(card);
  }

  function renderVideoCard(container, titleText, url) {
    container.innerHTML = '';
    const card = document.createElement('div'); card.className = 'card result';
    const title = document.createElement('h2'); title.textContent = titleText || '影片結果';
    const video = document.createElement('video'); video.controls = true; video.loop = true; video.muted = true; video.src = url; video.playsInline = true;
    card.appendChild(title); card.appendChild(video);
    container.appendChild(card);
  }

  // Fetch model options from backend and inject dropdowns into forms
  async function injectModelDropdowns() {
    try {
      const res = await fetch('/models/options');
      if (!res.ok) return;
      const opts = await res.json();
      const ckptChoices = Array.isArray(opts.ckpt_choices) ? opts.ckpt_choices : [];
      const vaeChoices = Array.isArray(opts.vae_choices) ? opts.vae_choices : [];
      const recCkpt = opts.recommended_ckpt || '';
      const recVae = opts.recommended_vae || '';
      const selCkpt = opts.selected_ckpt || '';
      const selVae = opts.selected_vae || '';

      function buildSelect(name, choices, recommended, selected) {
        const wrap = document.createElement('div');
        const label = document.createElement('label');
        label.textContent = name === 'ckpt_name' ? '模型 (Checkpoint)' : 'VAE';
        const sel = document.createElement('select');
        sel.name = name;
        const def = document.createElement('option');
        def.value = '';
        def.textContent = '自動/預設' + (recommended ? `（推薦：${recommended}）` : '');
        sel.appendChild(def);
        choices.forEach((c) => {
          const o = document.createElement('option');
          o.value = c; o.textContent = c;
          if ((selected && selected === c) || (!selected && recommended && recommended === c)) o.selected = true;
          sel.appendChild(o);
        });
        wrap.appendChild(label); wrap.appendChild(sel);
        return wrap;
      }

      function insertRowBefore(form, beforeEl) {
        const row = document.createElement('div');
        row.className = 'row';
        row.appendChild(buildSelect('ckpt_name', ckptChoices, recCkpt, selCkpt));
        row.appendChild(buildSelect('vae_name', vaeChoices, recVae, selVae));
        form.insertBefore(row, beforeEl);
      }

      // t2i
      const t2iForm = document.getElementById('t2iForm');
      if (t2iForm) {
        const neg = t2iForm.querySelector('input[name="negative"]');
        if (neg && !t2iForm.querySelector('select[name="ckpt_name"]')) insertRowBefore(t2iForm, neg);
      }
      // i2i (replace text inputs if present)
      const i2iForm = document.getElementById('i2iForm');
      if (i2iForm) {
        const ckptInput = i2iForm.querySelector('input[name="ckpt_name"]');
        const vaeInput = i2iForm.querySelector('input[name="vae_name"]');
        if (ckptInput && vaeInput) {
          const row = ckptInput.closest('.row') || vaeInput.closest('.row') || i2iForm;
          const parent = row.parentNode;
          const anchor = row.nextSibling;
          // remove old row and insert new selects row in its place
          row.remove();
          const newRow = document.createElement('div');
          newRow.className = 'row';
          newRow.appendChild(buildSelect('ckpt_name', ckptChoices, recCkpt, selCkpt));
          newRow.appendChild(buildSelect('vae_name', vaeChoices, recVae, selVae));
          parent.insertBefore(newRow, anchor);
        } else {
          const wfPath = i2iForm.querySelector('input[name="workflow_path"]');
          if (wfPath && !i2iForm.querySelector('select[name="ckpt_name"]')) insertRowBefore(i2iForm, wfPath);
        }
      }
      // inpaint
      const inpaintForm = document.getElementById('inpaintForm');
      if (inpaintForm) {
        const neg = inpaintForm.querySelector('input[name="negative"]');
        if (neg && !inpaintForm.querySelector('select[name="ckpt_name"]')) insertRowBefore(inpaintForm, neg);
      }

      // After injecting dropdowns, auto-populate recommended defaults
      try { autopopulateDefaults(opts); } catch {}
    } catch {}
  }

  // Kick off model dropdown population
  try { injectModelDropdowns(); } catch {}

  // Auto-fill sensible default parameters if fields are empty
  function autopopulateDefaults(opts) {
    const isXL = (opts && typeof opts.recommended_ckpt === 'string' && /\bxl\b|sdxl/i.test(opts.recommended_ckpt)) ? true : false;
    const defSize = isXL ? { w: 1024, h: 1024 } : { w: 768, h: 768 };
    const defStepsT2I = isXL ? 35 : 28;
    const defStepsI2I = 20;
    const defCfg = 6.5;
    const defDenoise = 0.55;
    const defSampler = 'dpmpp_2m';
    const defScheduler = 'karras';

    function setIfEmpty(input, val) {
      if (!input) return;
      const v = (input.value || '').trim();
      if (v === '') input.value = String(val);
    }

    async function ensureNegative(el) {
      if (!el || (el.value && el.value.trim() !== '')) return;
      try { const r = await fetch('/prompt/presets'); if (!r.ok) return; const j = await r.json(); el.value = j.negative_default || el.value; } catch {}
    }

    // t2i
    const t2iForm = document.getElementById('t2iForm');
    if (t2iForm) {
      setIfEmpty(t2iForm.querySelector('input[name="width"]'), defSize.w);
      setIfEmpty(t2iForm.querySelector('input[name="height"]'), defSize.h);
      setIfEmpty(t2iForm.querySelector('input[name="steps"]'), defStepsT2I);
      setIfEmpty(t2iForm.querySelector('input[name="cfg"]'), defCfg);
      // Negative default
      ensureNegative(t2iForm.querySelector('input[name="negative"]'));
    }

    // i2i
    const i2iForm = document.getElementById('i2iForm');
    if (i2iForm) {
      setIfEmpty(i2iForm.querySelector('input[name="width"]'), defSize.w);
      setIfEmpty(i2iForm.querySelector('input[name="height"]'), defSize.h);
      setIfEmpty(i2iForm.querySelector('input[name="steps"]'), defStepsI2I);
      setIfEmpty(i2iForm.querySelector('input[name="cfg"]'), defCfg);
      setIfEmpty(i2iForm.querySelector('input[name="denoise"]'), defDenoise);
      setIfEmpty(i2iForm.querySelector('input[name="sampler_name"]'), defSampler);
      setIfEmpty(i2iForm.querySelector('input[name="scheduler"]'), defScheduler);
      ensureNegative(i2iForm.querySelector('input[name="negative"]'));
    }

    // inpaint
    const inpaintForm = document.getElementById('inpaintForm');
    if (inpaintForm) {
      ensureNegative(inpaintForm.querySelector('input[name="negative"]'));
    }
  }

  function uploadXHR(url, formData, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest(); xhr.open('POST', url, true);
      xhr.onload = () => { try { resolve({ ok: xhr.status >= 200 && xhr.status < 300, json: JSON.parse(xhr.responseText) }); } catch (e) { reject(e); } };
      xhr.onerror = () => reject(new Error('Network error'));
      if (xhr.upload && onProgress) xhr.upload.onprogress = (ev) => { if (ev.lengthComputable) onProgress(Math.round(ev.loaded * 100 / ev.total)); };
      xhr.send(formData);
    });
  }

  async function submitWithBusy(form, msgEl, url, onSuccess) {
    const btn = form.querySelector('button[type="submit"], .btn'); if (btn) btn.disabled = true;
    msgEl.textContent = '⌛ 處理中...'; const prog = form.querySelector('.progress');
    try {
      const fd = new FormData(form); if (prog) prog.style.display = 'block';
      const r = await uploadXHR(url, fd, (pct) => { const bar = prog && prog.querySelector('.bar'); if (bar) bar.style.width = pct + '%'; });
      const j = r.json; if (r.ok) { showOk(msgEl, j.message || '完成'); toast('完成', 'success'); if (onSuccess) onSuccess(j); }
      else { showError(msgEl, j); toast(j.error || '失敗', 'error'); }
    } catch (err) { showError(msgEl, String(err)); toast('連線失敗', 'error'); }
    finally { if (btn) btn.disabled = false; if (prog) { const bar = prog.querySelector('.bar'); if (bar) bar.style.width = '0%'; prog.style.display = 'none'; } }
  }

  function bindDropzone(form, fileInput, onPreview) {
    if (!form) return;
    form.addEventListener('dragover', (e) => { e.preventDefault(); form.classList.add('dragover'); });
    form.addEventListener('dragleave', () => form.classList.remove('dragover'));
    form.addEventListener('drop', (e) => { e.preventDefault(); form.classList.remove('dragover'); const files = e.dataTransfer.files; if (files && files[0]) { if (fileInput) fileInput.files = files; if (onPreview) onPreview(files[0]); } });
  }

  // Try-on Step 1
  const form1 = document.getElementById('form1'); const p1msg = document.getElementById('p1msg');
  let personUploaded = false;
  if (form1 && p1msg) {
    const file1 = form1.querySelector('input[type="file"][name="image"]'); const p1prev = document.getElementById('p1preview');
    function showPrev1(f) { if (!p1prev) return; const r = new FileReader(); r.onload = () => { p1prev.innerHTML=''; const im=new Image(); im.src=r.result; p1prev.appendChild(im); }; r.readAsDataURL(f); }
    if (file1) file1.addEventListener('change', e => { const f = e.target.files[0]; if (f) showPrev1(f); });
    bindDropzone(form1, file1, showPrev1);
    form1.addEventListener('submit', async (e) => { e.preventDefault(); await submitWithBusy(form1, p1msg, '/upload1', () => { personUploaded = true; toast('人物已上傳', 'success'); }); });
  }

  // Try-on Step 2
  const form2 = document.getElementById('form2'); const p2msg = document.getElementById('p2msg'); const resultDiv = document.getElementById('result');
  if (form2 && p2msg && resultDiv) {
    const file2 = form2.querySelector('input[type="file"][name="image"]'); const p2prev = document.getElementById('p2preview');
    function showPrev2(f) { if (!p2prev) return; const r = new FileReader(); r.onload = () => { p2prev.innerHTML=''; const im=new Image(); im.src=r.result; p2prev.appendChild(im); }; r.readAsDataURL(f); }
    if (file2) file2.addEventListener('change', e => { const f = e.target.files[0]; if (f) showPrev2(f); });
    bindDropzone(form2, file2, showPrev2);
    form2.addEventListener('submit', async (e) => { e.preventDefault(); if (!personUploaded) { toast('請先上傳人物照', 'error'); return; } await submitWithBusy(form2, p2msg, '/upload2', (j) => { renderImageCard(resultDiv, '最新結果', j.download); }); });
  }

  // Text -> Image
  const t2iForm = document.getElementById('t2iForm'); const t2iMsg = document.getElementById('t2iMsg'); const t2iResult = document.getElementById('t2iResult');
  if (t2iForm && t2iMsg && t2iResult) {
    const t2iStyle = document.getElementById('t2iStyle'); const t2iOptimize = document.getElementById('t2iOptimize'); const t2iFillNeg = document.getElementById('t2iFillNeg');
    if (t2iOptimize) t2iOptimize.addEventListener('click', async () => { const promptInput = t2iForm.querySelector('input[name="prompt"]'); const style = (t2iStyle && t2iStyle.value) || ''; const res = await fetch('/prompt/expand', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt: promptInput.value, style, include_quality: 1 }) }); const j = await res.json(); if (res.ok) { promptInput.value = j.prompt; const neg = t2iForm.querySelector('input[name="negative"]'); if (neg && (!neg.value || neg.value.length < 3)) neg.value = j.negative_suggestion; } else { toast('優化失敗', 'error'); } });
    if (t2iFillNeg) t2iFillNeg.addEventListener('click', async () => { try { const res = await fetch('/prompt/presets'); const j = await res.json(); const neg = t2iForm.querySelector('input[name="negative"]'); if (neg) neg.value = j.negative_default; } catch {} });
    t2iForm.addEventListener('submit', async (e) => { e.preventDefault(); await submitWithBusy(t2iForm, t2iMsg, '/text2image', (j) => { renderImageCard(t2iResult, '最新結果', j.download); }); });
  }

  // Image -> Image
  const i2iForm = document.getElementById('i2iForm'); const i2iMsg = document.getElementById('i2iMsg'); const i2iResult = document.getElementById('i2iResult');
  if (i2iForm && i2iMsg && i2iResult) {
    const i2iStyle = document.getElementById('i2iStyle'); const i2iOptimize = document.getElementById('i2iOptimize'); const i2iFillNeg = document.getElementById('i2iFillNeg');
    if (i2iOptimize) i2iOptimize.addEventListener('click', async () => { const promptInput = i2iForm.querySelector('input[name="prompt"]'); const style = (i2iStyle && i2iStyle.value) || ''; const res = await fetch('/prompt/expand', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt: promptInput.value, style, include_quality: 1 }) }); const j = await res.json(); if (res.ok) { promptInput.value = j.prompt; const neg = i2iForm.querySelector('input[name="negative"]'); if (neg && (!neg.value || neg.value.length < 3)) neg.value = j.negative_suggestion; } else { toast('優化失敗', 'error'); } });
    if (i2iFillNeg) i2iFillNeg.addEventListener('click', async () => { try { const res = await fetch('/prompt/presets'); const j = await res.json(); const neg = i2iForm.querySelector('input[name="negative"]'); if (neg) neg.value = j.negative_default; } catch {} });
    i2iForm.addEventListener('submit', async (e) => { e.preventDefault(); await submitWithBusy(i2iForm, i2iMsg, '/img2img', (j) => { renderImageCard(i2iResult, '最新結果', j.download); }); });
  }

  // Inpaint
  const inpaintForm = document.getElementById('inpaintForm'); const inpaintMsg = document.getElementById('inpaintMsg'); const inpaintResult = document.getElementById('inpaintResult');
  if (inpaintForm && inpaintMsg && inpaintResult) {
    const inpaintStyle = document.getElementById('inpaintStyle'); const inpaintOptimize = document.getElementById('inpaintOptimize'); const inpaintFillNeg = document.getElementById('inpaintFillNeg');
    if (inpaintOptimize) inpaintOptimize.addEventListener('click', async () => { const promptInput = inpaintForm.querySelector('input[name="prompt"]'); const style = (inpaintStyle && inpaintStyle.value) || ''; const res = await fetch('/prompt/expand', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt: promptInput.value, style, include_quality: 1 }) }); const j = await res.json(); if (res.ok) { promptInput.value = j.prompt; const neg = inpaintForm.querySelector('input[name="negative"]'); if (neg && (!neg.value || neg.value.length < 3)) neg.value = j.negative_suggestion; } else { toast('優化失敗', 'error'); } });
    if (inpaintFillNeg) inpaintFillNeg.addEventListener('click', async () => { try { const res = await fetch('/prompt/presets'); const j = await res.json(); const neg = inpaintForm.querySelector('input[name="negative"]'); if (neg) neg.value = j.negative_default; } catch {} });
    inpaintForm.addEventListener('submit', async (e) => { e.preventDefault(); await submitWithBusy(inpaintForm, inpaintMsg, '/inpaint', (j) => { renderImageCard(inpaintResult, '最新結果', j.download); }); });
  }

  // Image -> Video
  const i2vForm = document.getElementById('i2vForm');
  const i2vMsg = document.getElementById('i2vMsg');
  const i2vResult = document.getElementById('i2vResult');
  const i2vPreview = document.getElementById('i2vPreview');
  if (i2vForm && i2vMsg && i2vResult) {
    const file = i2vForm.querySelector('input[type="file"][name="image"]');
    function showPrev(f) { if (!i2vPreview) return; const r=new FileReader(); r.onload=()=>{ i2vPreview.innerHTML=''; const im=new Image(); im.src=r.result; i2vPreview.appendChild(im); }; r.readAsDataURL(f); }
    if (file) file.addEventListener('change', e => { const f=e.target.files[0]; if (f) showPrev(f); });
    bindDropzone(i2vForm, file, showPrev);
    i2vForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      await submitWithBusy(i2vForm, i2vMsg, '/img2vid', (j) => {
        renderVideoCard(i2vResult, '影片結果', j.download);
      });
    });
  }
});

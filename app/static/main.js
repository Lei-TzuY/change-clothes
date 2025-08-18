
// app/static/main.js
document.addEventListener('DOMContentLoaded', () => {
  let personUploaded = false;

  // 人物圖上傳
  const form1 = document.getElementById('form1');
  const p1msg = document.getElementById('p1msg');
  form1.addEventListener('submit', async e => {
    e.preventDefault();
    const fm = new FormData(form1);
    p1msg.textContent = '⏳ 處理中…';
    try {
      const res = await fetch('/upload1', { method: 'POST', body: fm });
      const j = await res.json();
      if (res.ok) {
        personUploaded = true;
        p1msg.textContent = '✅ ' + j.message;
      } else {
        p1msg.textContent = '❌ ' + j.error;
      }
    } catch (err) {
      p1msg.textContent = '❌ 網路錯誤，請稍後再試';
    }
  });

  // 衣服圖上傳並顯示結果
  const form2 = document.getElementById('form2');
  const p2msg = document.getElementById('p2msg');
  const resultDiv = document.getElementById('result');  // ← 結果容器
  form2.addEventListener('submit', async e => {
    e.preventDefault();
    if (!personUploaded) {
      return alert('⚠️ 請先上傳人物圖！');
    }
    const fm = new FormData(form2);
    p2msg.textContent = '⏳ 合成中…';
    try {
      const res = await fetch('/upload2', { method: 'POST', body: fm });
      const j = await res.json();
      if (res.ok) {
        p2msg.textContent = '✅ ' + j.message;

        // —— 這裡開始清空舊結果、插入新結果 —— //
        resultDiv.innerHTML = '';

        const card = document.createElement('div');
        card.className = 'card result';

        const title = document.createElement('h2');
        title.textContent = '最新結果';

        const imgEl = document.createElement('img');
        imgEl.src = j.download;
        imgEl.style.maxWidth = '80%';

        card.appendChild(title);
        card.appendChild(imgEl);
        resultDiv.appendChild(card);
        // ———————————————————————————————— //

      } else {
        p2msg.textContent = '❌ ' + j.error;
      }
    } catch (err) {
      p2msg.textContent = '❌ 網路錯誤，請稍後再試';
    }
  });
});
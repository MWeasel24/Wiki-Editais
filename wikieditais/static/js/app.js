document.addEventListener('submit', async (e) => {
  const form = e.target;
  if (form.id !== 'chat-form') return;
  e.preventDefault();
  const input = form.querySelector('input[name="question"]');
  const box = document.getElementById('chat-box');
  const q = input.value.trim();
  if (!q) return;
  box.insertAdjacentHTML('beforeend', `<div class="msg user">${q.replace(/</g,'&lt;')}</div>`);
  input.value = '';
  box.insertAdjacentHTML('beforeend', `<div class="msg bot loading">Pensando...</div>`);
  const loading = box.querySelector('.loading');
  const fd = new FormData(); fd.append('question', q);
  try {
    const res = await fetch(form.dataset.url, {method:'POST', body:fd});
    const data = await res.json();
    loading.classList.remove('loading');
    loading.textContent = data.answer || 'Não consegui responder.';
  } catch(err) {
    loading.classList.remove('loading'); loading.textContent='Erro ao consultar o chat.';
  }
  box.scrollTop = box.scrollHeight;
});

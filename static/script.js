document.addEventListener('DOMContentLoaded', () => {
  const uploadForm = document.getElementById('upload-form');
  const uploadPanel = document.getElementById('upload-progress');
  const uploadLog = document.getElementById('progress-log');
  const uploadPercent = document.getElementById('progress-percent');
  const uploadStage = document.getElementById('progress-stage');
  const uploadBar = document.getElementById('progress-bar');
  const uploadSub = document.getElementById('progress-sub');

  if (uploadForm && uploadPanel && uploadLog && uploadPercent && uploadStage && uploadBar) {
    uploadForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = uploadForm.querySelector('button[type="submit"]');
      const formData = new FormData(uploadForm);
      uploadPanel.classList.remove('hidden');
      uploadPercent.textContent = '0%';
      uploadStage.textContent = 'Enviando PDF';
      uploadBar.style.width = '0%';
      uploadLog.textContent = 'Arquivo sendo enviado…';
      if (uploadSub) uploadSub.textContent = 'Tempo decorrido: 0s';
      if (button) {
        button.disabled = true;
        button.textContent = 'Processando…';
      }

      try {
        const startResp = await fetch('/upload/start', { method: 'POST', body: formData });
        const startData = await startResp.json();
        if (!startResp.ok || !startData.ok) throw new Error(startData.error || 'Falha ao iniciar processamento.');
        const jobId = startData.job_id;
        const poll = window.setInterval(async () => {
          try {
            const resp = await fetch(`/progresso/${jobId}`);
            const data = await resp.json();
            const pct = Math.max(0, Math.min(100, Number(data.pct || 0)));
            uploadPercent.textContent = `${Math.round(pct)}%`;
            uploadBar.style.width = `${pct}%`;
            uploadStage.textContent = data.etapa || 'Processando';
            uploadLog.textContent = data.detalhe || 'Processando…';
            if (uploadSub) uploadSub.textContent = `Tempo decorrido: ${data.elapsed || 0}s`;
            if (data.done) {
              window.clearInterval(poll);
              if (data.ok && data.redirect) {
                uploadPercent.textContent = '100%';
                uploadBar.style.width = '100%';
                uploadStage.textContent = 'Concluído';
                window.location.href = data.redirect;
              } else {
                uploadStage.textContent = 'Erro';
                uploadLog.textContent = data.error || 'Erro ao processar PDF.';
                if (button) {
                  button.disabled = false;
                  button.textContent = 'Processar PDF';
                }
              }
            }
          } catch (err) {
            window.clearInterval(poll);
            uploadStage.textContent = 'Erro';
            uploadLog.textContent = String(err);
            if (button) {
              button.disabled = false;
              button.textContent = 'Processar PDF';
            }
          }
        }, 700);
      } catch (err) {
        uploadStage.textContent = 'Erro';
        uploadLog.textContent = String(err.message || err);
        if (button) {
          button.disabled = false;
          button.textContent = 'Processar PDF';
        }
      }
    });
  }

  const chatForm = document.getElementById('chat-form');
  const chatProgress = document.getElementById('chat-progress');
  if (chatForm && chatProgress) {
    chatProgress.classList.add('hidden');
    chatProgress.classList.remove('active');
    chatProgress.style.display = 'none';
    chatProgress.textContent = '';
    const chatSteps = ['Consultando mapa do edital…', 'Buscando no RAG vetorial…', 'Montando resposta com fontes…'];
    let chatTimer = null;
    chatForm.addEventListener('submit', (event) => {
      const textarea = chatForm.querySelector('textarea[name="question"]');
      if (!textarea || !textarea.value.trim()) {
        event.preventDefault();
        return;
      }
      chatProgress.classList.remove('hidden');
      chatProgress.classList.add('active');
      chatProgress.style.display = 'block';
      const button = chatForm.querySelector('button[type="submit"]');
      if (button) {
        button.disabled = true;
        button.textContent = 'Processando…';
      }
      let i = 0;
      chatProgress.textContent = chatSteps[i];
      if (chatTimer) window.clearInterval(chatTimer);
      chatTimer = window.setInterval(() => {
        i = Math.min(i + 1, chatSteps.length - 1);
        chatProgress.textContent = chatSteps[i];
      }, 1300);
    });
  }
});

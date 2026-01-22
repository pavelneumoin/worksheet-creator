document.getElementById('uploadZone').addEventListener('click', () => {
    document.getElementById('fileInput').click();
});

document.getElementById('fileInput').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    // Get selected task count
    const taskCount = document.querySelector('input[name="taskCount"]:checked').value;
    formData.append('task_count', taskCount);

    // Get topic
    const topic = document.getElementById('topicInput').value || 'Рабочий лист';
    formData.append('topic', topic);

    // Get teacher name
    const teacherName = document.getElementById('teacherNameInput').value || '';
    formData.append('teacher_name', teacherName);

    // Get selected model
    const gigaModel = document.querySelector('input[name="gigaModel"]:checked').value;
    formData.append('model', gigaModel);

    const statusDiv = document.getElementById('status');
    statusDiv.innerHTML = '<p>Обработка... Пожалуйста, подождите.</p><div class="loader"></div>';

    try {
        const response = await fetch('/api/process', {
            method: 'POST',
            body: formData
        });
        const result = await response.json();

        if (response.ok) {
            // Store LaTeX code for modal
            window.currentLatexCode = result.latex_code || '';

            statusDiv.innerHTML = `
                <p class="success">Готово! ✅</p>
                <div class="result-buttons">
                    <div class="action-group">
                        <a href="${result.pdf_url}" target="_blank" class="action-btn primary">
                            <ion-icon name="download-outline"></ion-icon>
                            Скачать Вариант 1
                        </a>
                        <button id="genSimilarBtn" class="action-btn secondary">
                            <ion-icon name="sparkles-outline"></ion-icon>
                            Создать Вариант 2
                        </button>
                    </div>
                    <div class="action-group">
                        <button id="showLatexBtn" class="action-btn tertiary">
                            <ion-icon name="code-slash-outline"></ion-icon>
                            Получить LaTeX код
                        </button>
                    </div>
                    <div id="status2"></div>
                </div>
            `;

            // Handle "Show LaTeX" click
            document.getElementById('showLatexBtn').addEventListener('click', () => {
                showLatexModal(window.currentLatexCode || 'LaTeX код недоступен. Попробуйте сгенерировать документ ещё раз.');
            });

            // Handle "Generate Similar" click
            document.getElementById('genSimilarBtn').addEventListener('click', async () => {
                const btn = document.getElementById('genSimilarBtn');
                const status2 = document.getElementById('status2');

                btn.disabled = true;
                btn.innerHTML = '<ion-icon name="hourglass-outline"></ion-icon> Генерация...';
                status2.innerHTML = '<div class="loader small"></div>';

                try {
                    const formData2 = new FormData();
                    formData2.append('original_text', result.original_text);
                    formData2.append('task_count', taskCount);
                    formData2.append('model', gigaModel);
                    formData2.append('topic', topic);
                    formData2.append('teacher_name', teacherName);

                    const resp2 = await fetch('/api/generate_similar', {
                        method: 'POST',
                        body: formData2
                    });
                    const res2 = await resp2.json();

                    if (resp2.ok) {
                        // Store LaTeX code for variant 2
                        window.currentLatexCode2 = res2.latex_code || '';

                        status2.innerHTML = `
                            <div class="action-group" style="margin-top: 12px;">
                                <a href="${res2.pdf_url}" target="_blank" class="action-btn primary">
                                    <ion-icon name="download-outline"></ion-icon>
                                    Скачать Вариант 2
                                </a>
                                <button onclick="showLatexModal(window.currentLatexCode2 || 'LaTeX код недоступен')" class="action-btn tertiary">
                                    <ion-icon name="code-slash-outline"></ion-icon>
                                    LaTeX Варианта 2
                                </button>
                            </div>
                        `;
                        btn.innerHTML = '<ion-icon name="checkmark-circle-outline"></ion-icon> Готово!';
                    } else {
                        status2.innerHTML = `<span class="error">Ошибка: ${res2.error}</span>`;
                        btn.innerHTML = '<ion-icon name="alert-circle-outline"></ion-icon> Ошибка';
                        btn.disabled = false;
                    }
                } catch (err) {
                    status2.innerHTML = `<span class="error">Ошибка сети: ${err.message}</span>`;
                    btn.disabled = false;
                }
            });
        } else {
            statusDiv.innerHTML = `<p class="error">Ошибка: ${result.error}</p>`;
        }
    } catch (error) {
        statusDiv.innerHTML = `<p class="error">Ошибка сети: ${error.message}</p>`;
        console.error(error);
    }
});

// LaTeX Modal Function
function showLatexModal(latexCode) {
    // Remove existing modal if any
    const existingModal = document.querySelector('.latex-modal-overlay');
    if (existingModal) {
        existingModal.remove();
    }

    const modalHTML = `
        <div class="latex-modal-overlay" onclick="closeLatexModal(event)">
            <div class="latex-modal" onclick="event.stopPropagation()">
                <div class="latex-modal-header">
                    <h3>
                        <ion-icon name="code-slash-outline"></ion-icon>
                        LaTeX код документа
                    </h3>
                    <button class="modal-close-btn" onclick="closeLatexModal()">
                        <ion-icon name="close-outline"></ion-icon>
                    </button>
                </div>
                <div class="latex-modal-body">
                    <div class="latex-code-container">
                        <div class="latex-code-header">
                            <span>document.tex</span>
                            <button class="copy-btn" onclick="copyLatexCode()">
                                <ion-icon name="copy-outline"></ion-icon>
                                Копировать
                            </button>
                        </div>
                        <pre class="latex-code" id="latexCodeContent">${escapeHtml(latexCode)}</pre>
                    </div>
                </div>
                <div class="latex-modal-footer">
                    <a href="https://www.overleaf.com/project" target="_blank" class="external-link-btn">
                        <ion-icon name="open-outline"></ion-icon>
                        Открыть в Overleaf
                    </a>
                    <a href="https://papeeria.com/" target="_blank" class="external-link-btn">
                        <ion-icon name="open-outline"></ion-icon>
                        Открыть в Papeeria
                    </a>
                    <a href="https://latexbase.com/" target="_blank" class="external-link-btn">
                        <ion-icon name="open-outline"></ion-icon>
                        LaTeX Base
                    </a>
                </div>
            </div>
        </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHTML);
    document.body.style.overflow = 'hidden';
}

// Close modal function
function closeLatexModal(event) {
    if (event && event.target !== event.currentTarget) return;
    const modal = document.querySelector('.latex-modal-overlay');
    if (modal) {
        modal.remove();
        document.body.style.overflow = '';
    }
}

// Copy LaTeX code to clipboard
async function copyLatexCode() {
    const codeElement = document.getElementById('latexCodeContent');
    const copyBtn = document.querySelector('.copy-btn');

    try {
        await navigator.clipboard.writeText(codeElement.textContent);
        copyBtn.classList.add('copied');
        copyBtn.innerHTML = '<ion-icon name="checkmark-outline"></ion-icon> Скопировано!';

        setTimeout(() => {
            copyBtn.classList.remove('copied');
            copyBtn.innerHTML = '<ion-icon name="copy-outline"></ion-icon> Копировать';
        }, 2000);
    } catch (err) {
        console.error('Failed to copy:', err);
        copyBtn.innerHTML = '<ion-icon name="alert-circle-outline"></ion-icon> Ошибка';
    }
}

// Escape HTML for safe display
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Close modal on Escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeLatexModal();
    }
});

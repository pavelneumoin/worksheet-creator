document.getElementById('uploadZone').addEventListener('click', () => {
    document.getElementById('fileInput').click();
});

document.getElementById('fileInput').addEventListener('change', async (e) => {
    const files = e.target.files;
    if (files.length === 0) return;

    const formData = new FormData();
    for (let i = 0; i < files.length; i++) {
        formData.append('files', files[i]);
    }

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
            // Store LaTeX code
            window.currentLatexCode = result.latex_code || '';

            statusDiv.innerHTML = `
                <p class="success">Текст распознан! ✅</p>
                <div class="editor-container">
                    <div class="editor-header">
                        <span><ion-icon name="code-slash-outline"></ion-icon> Редактор LaTeX (проверьте код перед печатью)</span>
                    </div>
                    <textarea id="latexEditorInput" class="latex-textarea">${escapeHtml(window.currentLatexCode)}</textarea>
                </div>
                <div class="result-buttons">
                    <div class="action-group">
                        <button id="compilePdfBtn" class="action-btn primary">
                            <ion-icon name="document-text-outline"></ion-icon>
                            Сгенерировать PDF
                        </button>
                    </div>
                    <div id="statusCompile"></div>
                    <div class="action-group" style="margin-top: 15px;">
                        <button id="showLatexBtn" class="action-btn tertiary">
                            <ion-icon name="code-slash-outline"></ion-icon>
                            Код в отдельном окне
                        </button>
                    </div>
                    <div id="status2"></div>
                </div>
            `;

            // Handle "Compile PDF" click
            document.getElementById('compilePdfBtn').addEventListener('click', async () => {
                const compileBtn = document.getElementById('compilePdfBtn');
                const statusCompile = document.getElementById('statusCompile');
                const currentCode = document.getElementById('latexEditorInput').value;
                const layout = document.querySelector('input[name="layout"]:checked').value;

                compileBtn.disabled = true;
                compileBtn.innerHTML = '<ion-icon name="hourglass-outline"></ion-icon> Компиляция...';
                statusCompile.innerHTML = '<div class="loader small"></div>';

                try {
                    const compileResp = await fetch('/api/compile', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            latex_code: currentCode,
                            topic: topic,
                            teacher_name: teacherName,
                            is_variant2: false,
                            layout: layout
                        })
                    });
                    const compileRes = await compileResp.json();

                    if (compileResp.ok) {
                        statusCompile.innerHTML = `
                            <div class="action-group" style="margin-top: 12px; margin-bottom: 20px;">
                                <a href="${compileRes.pdf_url}" target="_blank" class="action-btn primary">
                                    <ion-icon name="download-outline"></ion-icon>
                                    Скачать Вариант 1
                                </a>
                                ${compileRes.keys_url ? `
                                <a href="${compileRes.keys_url}" target="_blank" class="action-btn tertiary">
                                    <ion-icon name="key-outline"></ion-icon>
                                    Ответы В1
                                </a>` : ''}
                            </div>
                            <div class="action-group" style="flex-direction: column; align-items: center; gap: 8px;">
                                <select id="variantDifficulty" class="topic-input" style="max-width: 250px; text-align: center;">
                                    <option value="same">Сложность: Такая же</option>
                                    <option value="easier">Сложность: Проще</option>
                                    <option value="harder">Сложность: Сложнее</option>
                                </select>
                                <button id="genSimilarBtn" class="action-btn secondary" style="width: 250px;">
                                    <ion-icon name="sparkles-outline"></ion-icon>
                                    Создать Вариант 2
                                </button>
                            </div>
                        `;
                        compileBtn.style.display = 'none'; // Скрываем кнопку компиляции после успеха

                        // Attach Event Listener for Variant 2 Generation AFTER the button is added to DOM
                        document.getElementById('genSimilarBtn').addEventListener('click', generateSimilarVariant);

                    } else {
                        statusCompile.innerHTML = `<span class="error">Ошибка: ${compileRes.error}</span>`;
                        compileBtn.innerHTML = '<ion-icon name="alert-circle-outline"></ion-icon> Ошибка';
                        compileBtn.disabled = false;
                    }
                } catch (err) {
                    statusCompile.innerHTML = `<span class="error">Ошибка сети: ${err.message}</span>`;
                    compileBtn.disabled = false;
                }
            });

            // Handle "Show LaTeX" in modal
            document.getElementById('showLatexBtn').addEventListener('click', () => {
                const currentCode = document.getElementById('latexEditorInput').value;
                showLatexModal(currentCode || 'Код недоступен.');
            });

            // Extract logic for generating similar variant into a separate function
            async function generateSimilarVariant() {
                const btn = document.getElementById('genSimilarBtn');
                const status2 = document.getElementById('status2');
                const currentCode = document.getElementById('latexEditorInput').value;
                const difficulty = document.getElementById('variantDifficulty')?.value || 'same';

                btn.disabled = true;
                btn.innerHTML = '<ion-icon name="hourglass-outline"></ion-icon> Генерация...';
                status2.innerHTML = '<div class="loader small"></div>';

                try {
                    const formData2 = new FormData();
                    formData2.append('original_text', currentCode);
                    formData2.append('difficulty', difficulty);
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

                        // Now we need to compile Variant 2
                        const layout2 = document.querySelector('input[name="layout"]:checked').value;
                        const compileResp2 = await fetch('/api/compile', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                latex_code: res2.latex_code,
                                topic: topic,
                                teacher_name: teacherName,
                                is_variant2: true,
                                layout: layout2
                            })
                        });
                        const compileRes2 = await compileResp2.json();

                        if (compileResp2.ok) {
                            status2.innerHTML = `
                                <div class="action-group" style="margin-top: 12px;">
                                    <a href="${compileRes2.pdf_url}" target="_blank" class="action-btn primary">
                                        <ion-icon name="download-outline"></ion-icon>
                                        Скачать Вариант 2
                                    </a>
                                    ${compileRes2.keys_url ? `
                                    <a href="${compileRes2.keys_url}" target="_blank" class="action-btn tertiary">
                                        <ion-icon name="key-outline"></ion-icon>
                                        Ответы В2
                                    </a>` : ''}
                                    <button onclick="showLatexModal(window.currentLatexCode2 || 'LaTeX код недоступен')" class="action-btn tertiary">
                                        <ion-icon name="code-slash-outline"></ion-icon>
                                        LaTeX Варианта 2
                                    </button>
                                </div>
                            `;
                            btn.innerHTML = '<ion-icon name="checkmark-circle-outline"></ion-icon> Готово!';
                        } else {
                            status2.innerHTML = `<span class="error">Ошибка компиляции В2: ${compileRes2.error}</span>`;
                            btn.innerHTML = '<ion-icon name="alert-circle-outline"></ion-icon> Ошибка';
                            btn.disabled = false;
                        }
                    } else {
                        status2.innerHTML = `<span class="error">Ошибка: ${res2.error}</span>`;
                        btn.innerHTML = '<ion-icon name="alert-circle-outline"></ion-icon> Ошибка';
                        btn.disabled = false;
                    }
                } catch (err) {
                    status2.innerHTML = `<span class="error">Ошибка сети: ${err.message}</span>`;
                    btn.disabled = false;
                }
            } // end of generateSimilarVariant
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

// Load History
async function loadHistory() {
    const historyContainer = document.getElementById('historyContainer');
    try {
        const response = await fetch('/api/history?limit=10');
        const data = await response.json();

        if (data.history && data.history.length > 0) {
            historyContainer.innerHTML = '';
            data.history.forEach(item => {
                const date = new Date(item.created_at).toLocaleString('ru-RU', {
                    day: '2-digit', month: '2-digit', year: 'numeric',
                    hour: '2-digit', minute: '2-digit'
                });

                const div = document.createElement('div');
                div.className = 'history-item';
                div.innerHTML = `
                    <div class="history-info">
                        <h4>${escapeHtml(item.topic || 'Без темы')}</h4>
                        <p>${date} | Учитель: ${escapeHtml(item.teacher_name || 'Не указан')}</p>
                    </div>
                    <div class="history-actions">
                        ${item.pdf_url ? `<a href="${item.pdf_url}" target="_blank" class="action-btn primary" title="Скачать PDF"><ion-icon name="document-text-outline"></ion-icon> PDF</a>` : ''}
                        ${item.keys_url ? `<a href="${item.keys_url}" target="_blank" class="action-btn tertiary" title="Скачать Ответы"><ion-icon name="key-outline"></ion-icon> Ключи</a>` : ''}
                        <button onclick="showLatexModal(this.dataset.code)" data-code="${escapeHtml(item.latex_code || '')}" class="action-btn secondary" title="Посмотреть код">
                            <ion-icon name="code-slash-outline"></ion-icon> Код
                        </button>
                    </div>
                `;
                historyContainer.appendChild(div);
            });
        } else {
            historyContainer.innerHTML = '<p style="color: var(--text-muted);">История пуста. Создайте свой первый рабочий лист!</p>';
        }
    } catch (err) {
        historyContainer.innerHTML = `<p class="error">Ошибка загрузки истории: ${err.message}</p>`;
    }
}

// Ensure history is loaded on page load
document.addEventListener('DOMContentLoaded', loadHistory);

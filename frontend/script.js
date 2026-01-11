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

    const statusDiv = document.getElementById('status');
    statusDiv.innerHTML = '<p>Обработка... Пожалуйста, подождите.</p><div class="loader"></div>';

    try {
        const response = await fetch('/api/process', {
            method: 'POST',
            body: formData
        });
        const result = await response.json();

        if (response.ok) {
            statusDiv.innerHTML = `
                <p class="success">Готово! ✅</p>
                <p>Распознанный текст: <em>${result.original_text.substring(0, 100)}...</em></p>
                <div class="result-buttons">
                    <a href="${result.pdf_url}" target="_blank" class="download-btn">Скачать Вариант 1</a>
                    <button id="genSimilarBtn" class="download-btn secondary-btn" style="margin-top: 10px;">Сгенерировать Похожий Вариант 2</button>
                    <div id="status2" style="margin-top: 10px;"></div>
                </div>
            `;

            // Handle "Generate Similar" click
            document.getElementById('genSimilarBtn').addEventListener('click', async () => {
                const btn = document.getElementById('genSimilarBtn');
                const status2 = document.getElementById('status2');

                btn.disabled = true;
                btn.textContent = "Генерация...";
                status2.innerHTML = '<div class="loader small"></div>';

                try {
                    const formData2 = new FormData();
                    formData2.append('original_text', result.original_text);
                    formData2.append('task_count', taskCount);

                    const resp2 = await fetch('/api/generate_similar', {
                        method: 'POST',
                        body: formData2
                    });
                    const res2 = await resp2.json();

                    if (resp2.ok) {
                        status2.innerHTML = `<a href="${res2.pdf_url}" target="_blank" class="download-btn">Скачать Вариант 2</a>`;
                        btn.textContent = "Вариант 2 Готов!";
                    } else {
                        status2.innerHTML = `<span class="error">Ошибка: ${res2.error}</span>`;
                        btn.textContent = "Ошибка";
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

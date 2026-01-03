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
                <a href="${result.pdf_url}" target="_blank" class="download-btn">Скачать Рабочий Лист</a>
            `;
        } else {
            statusDiv.innerHTML = `<p class="error">Ошибка: ${result.error}</p>`;
        }
    } catch (error) {
        statusDiv.innerHTML = `<p class="error">Ошибка сети: ${error.message}</p>`;
        console.error(error);
    }
});

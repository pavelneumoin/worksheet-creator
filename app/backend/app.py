"""Local worksheet API for reviewed mathematics and physics materials."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import tempfile
import uuid

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

from utils import latex as latex_engine
from utils.db import init_db, save_worksheet, get_history
from utils.gigachat_client import (
    AIServiceError, get_ai_status, process_image_with_gigachat, generate_similar_worksheet,
)

app = Flask(__name__, static_folder="../frontend", static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
UPLOAD_FOLDER = Path(__file__).resolve().parent / "uploads"
UPLOAD_FOLDER.mkdir(exist_ok=True)
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)
init_db()

MAX_FILES = 10
SUBJECTS = {"math", "physics"}
ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg"}
DEMO_MESSAGE = "Учебный пример подготовлен вручную. ИИ не использовался."
DEMOS = {
    "math": {
        "topic": "Математика: уравнения, дроби и корни",
        "latex_code": r"""
\TaskBox{1}{Решите квадратное уравнение $x^2-5x+6=0$.}
\WriteField{35mm}
\TaskBox{2}{Вычислите $\dfrac{3}{4}+\dfrac{5}{6}$. Ответ запишите несократимой дробью.}
\WriteField{35mm}
\TaskBox{3}{Вычислите $\sqrt{81}+\sqrt{16}$.}
\WriteField{35mm}
\newpage
\section*{Ответы}
\begin{tabular}{|c|l|}
\hline
Задача & Ответ \\
\hline
1 & $x_1=2,\quad x_2=3$ \\
2 & $\dfrac{19}{12}$ \\
3 & $13$ \\
\hline
\end{tabular}
""".strip(),
    },
    "physics": {
        "topic": "Физика: движение, закон Ома и плотность",
        "latex_code": r"""
\TaskBox{1}{Тело движется равноускоренно: $v_0=2\,\text{м/с}$, $a=3\,\text{м/с}^2$, $t=4\,\text{с}$. Найдите путь по формуле $s=v_0t+\dfrac{at^2}{2}$.}
\WriteField{35mm}
\TaskBox{2}{Напряжение на резисторе $U=12\,\text{В}$, сопротивление $R=4\,\text{Ом}$. Найдите силу тока: $I=\dfrac{U}{R}$.}
\WriteField{35mm}
\TaskBox{3}{Масса образца $m=540\,\text{г}$, объём $V=200\,\text{см}^3$. Найдите плотность $\rho=\dfrac{m}{V}$ в $\text{г/см}^3$.}
\WriteField{35mm}
\newpage
\section*{Ответы}
\begin{tabular}{|c|l|}
\hline
Задача & Ответ \\
\hline
1 & $32\,\text{м}$ \\
2 & $3\,\text{А}$ \\
3 & $2{,}7\,\text{г/см}^3$ \\
\hline
\end{tabular}
""".strip(),
    },
}


def api_error(message, code, status):
    return jsonify({"error": message, "code": code}), status


@app.errorhandler(AIServiceError)
def ai_error(exc):
    return api_error(str(exc), exc.code, exc.status)


@app.errorhandler(RequestEntityTooLarge)
def upload_too_large(exc):
    return api_error("Размер всего запроса не должен превышать 20 МБ.",
                     "upload_too_large", 413)


@app.errorhandler(HTTPException)
def http_error(exc):
    if request.path.startswith(("/api/", "/worksheet-api/")):
        return api_error("Запрос не найден или имеет неверный формат.",
                         "http_error", exc.code or 400)
    return exc


@app.errorhandler(Exception)
def unexpected_error(exc):
    # Provider errors have a dedicated handler; never expose config or traceback.
    app.logger.error("Unexpected request failure (%s)", type(exc).__name__)
    return api_error("Не удалось выполнить запрос. Повторите позже или откройте ручной пример.",
                     "internal_error", 500)


def _subject(value):
    if value not in SUBJECTS:
        raise AIServiceError("Выберите математику или физику.", "invalid_subject", 400)
    return value


def _count(value):
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise AIServiceError("Количество задач на странице должно быть от 1 до 6.",
                             "invalid_task_count", 400)
    if result not in range(1, 7):
        raise AIServiceError("Количество задач на странице должно быть от 1 до 6.",
                             "invalid_task_count", 400)
    return result


def _compiler():
    resolver = getattr(latex_engine, "get_latex_compiler", None)
    return resolver() if resolver else None


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/status")
def status():
    result = get_ai_status()
    ready = bool(_compiler())
    result.update({
        "latex_ready": ready,
        "latex_mode": "local" if ready else "unavailable",
        "latex_message": ("Локальный компилятор найден. Можно проверить сборку примера."
                          if ready else "Локальный TeX-компилятор не найден. Примеры можно открыть и редактировать."),
        "demo_available": True,
        "supported_subjects": sorted(SUBJECTS),
        "supported_uploads": sorted(ALLOWED_SUFFIXES),
        "max_upload_mb": 20,
        "max_files": MAX_FILES,
    })
    return jsonify(result)


@app.route("/api/demo")
def demo():
    subject = _subject(request.args.get("subject", "math"))
    return jsonify({
        **DEMOS[subject], "subject": subject, "source": "manual_demo",
        "message": DEMO_MESSAGE, "requires_review": True,
    })


@app.route("/api/process", methods=["POST"])
def process_file():
    files = [f for f in request.files.getlist("files") if f and f.filename]
    if not files:
        return api_error("Выберите фотографии заданий.", "no_files", 400)
    if len(files) > MAX_FILES:
        return api_error("За один запрос можно загрузить не более 10 файлов.", "too_many_files", 400)
    subject = _subject(request.form.get("subject", "math"))
    count = _count(request.form.get("task_count", 3))
    model = request.form.get("model") or None
    for uploaded in files:
        suffix = Path(uploaded.filename).suffix.lower()
        if suffix == ".pdf":
            return api_error("PDF пока не поддерживается этим прототипом. Сохраните нужные страницы как PNG или JPEG.",
                             "pdf_not_supported", 415)
        if suffix not in ALLOWED_SUFFIXES:
            return api_error("Поддерживаются только изображения PNG и JPEG.", "unsupported_file_type", 415)
        header = uploaded.stream.read(8)
        uploaded.stream.seek(0)
        valid = (suffix == ".png" and header.startswith(b"\x89PNG\r\n\x1a\n")) or (
            suffix in {".jpg", ".jpeg"} and header.startswith(b"\xff\xd8\xff")
        )
        if not valid:
            return api_error("Содержимое файла не соответствует PNG или JPEG.",
                             "invalid_image", 415)
    # Validate configuration before persisting any source images.
    ai = get_ai_status()
    if model and model != ai["ai_model"]:
        return api_error("Используйте модель, настроенную на сервере.", "unsupported_model", 400)
    if not ai["ai_ready"]:
        return api_error(ai["ai_message"], "ai_not_configured" if not ai["ai_configured"]
                         else "ai_sdk_missing", 503)
    with tempfile.TemporaryDirectory(prefix="listok-", dir=app.config["UPLOAD_FOLDER"]) as tmp:
        paths = []
        for uploaded in files:
            path = Path(tmp) / (uuid.uuid4().hex + Path(uploaded.filename).suffix.lower())
            uploaded.save(path)
            paths.append(str(path))
        latex_content = process_image_with_gigachat(paths, task_count=count, model=model, subject=subject)
    return jsonify({"message": "Черновик готов. Проверьте задания и ответы.",
                    "latex_code": latex_content, "model": ai["ai_model"],
                    "subject": subject, "source": "ai_draft", "requires_review": True})


@app.route("/api/compile", methods=["POST"])
def compile_code():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return api_error("Ожидается JSON с полем latex_code.", "invalid_json", 400)
    content = data.get("latex_code")
    if not isinstance(content, str) or not content.strip():
        return api_error("Введите LaTeX-код рабочего листа.", "missing_latex", 400)
    topic = data.get("topic", "Рабочий лист")
    teacher = data.get("teacher_name", "")
    if not all(isinstance(value, str) and len(value) <= 200 for value in (topic, teacher)):
        return api_error("Тема и имя учителя должны быть строками до 200 символов.",
                         "invalid_metadata", 400)
    layout = data.get("layout", "1col")
    if not isinstance(layout, str) or layout not in {"1col", "2col"}:
        return api_error("Выберите одну или две колонки.", "invalid_layout", 400)
    variant = data.get("is_variant2", False)
    if not isinstance(variant, bool):
        return api_error("is_variant2 должен быть логическим значением.", "invalid_variant", 400)
    if not _compiler():
        return api_error("Локальный TeX-компилятор не найден. Настройте TeX и повторите сборку.",
                         "latex_unavailable", 503)
    base = ("variant2_" if variant else "worksheet_") + uuid.uuid4().hex
    title = f"{topic} (Вариант 2)" if variant else topic
    pdf, keys, error = latex_engine.compile_latex(
        content, topic=title, filename_base=base, teacher_name=teacher, layout=layout,
    )
    if error or not pdf:
        return api_error(str(error or "PDF не создан."), "latex_compile_failed", 422)
    pdf_url = f"/api/generated/{pdf}"
    keys_url = f"/api/generated/{keys}" if keys else None
    warnings = []
    try:
        save_worksheet(title, teacher, content, pdf_url, keys_url)
    except Exception as exc:
        app.logger.warning("Worksheet history could not be saved (%s)", type(exc).__name__)
        warnings.append("PDF готов, но сохранить запись в истории не удалось.")
    result = {"message": "PDF собран. Проверьте лист и ответы перед использованием.",
              "pdf_url": pdf_url, "warnings": warnings}
    if keys_url:
        result["keys_url"] = keys_url
    tex_path = Path(latex_engine.OUTPUT_DIR) / f"{base}.tex"
    if tex_path.is_file():
        result["tex_url"] = f"/api/generated/{tex_path.name}"
    return jsonify(result)


@app.route("/api/generate_similar", methods=["POST"])
def generate_similar():
    content = request.form.get("original_text", "")
    if not content.strip():
        return api_error("Передайте задания первого варианта.", "missing_original", 400)
    if len(content.encode("utf-8")) > 64 * 1024:
        return api_error("Исходный вариант слишком большой.", "original_too_large", 413)
    subject = _subject(request.form.get("subject", "math"))
    count = _count(request.form.get("task_count", 3))
    difficulty = request.form.get("difficulty", "same")
    if difficulty not in {"same", "easier", "harder"}:
        return api_error("Неизвестный уровень сложности.", "invalid_difficulty", 400)
    ai = get_ai_status()
    model = request.form.get("model") or None
    if model and model != ai["ai_model"]:
        return api_error("Используйте модель, настроенную на сервере.", "unsupported_model", 400)
    latex_content = generate_similar_worksheet(
        content, task_count=count, model=model,
        difficulty=difficulty, subject=subject,
    )
    return jsonify({"message": "Второй вариант подготовлен как черновик. Проверьте задания и ответы.",
                    "latex_code": latex_content, "source": "ai_draft", "subject": subject,
                    "requires_review": True, "model": ai["ai_model"]})


@app.route("/api/history")
def history():
    try:
        limit = int(request.args.get("limit", 50))
    except (TypeError, ValueError):
        return api_error("limit должен быть целым числом.", "invalid_limit", 400)
    if not 1 <= limit <= 100:
        return api_error("limit должен быть от 1 до 100.", "invalid_limit", 400)
    try:
        return jsonify({"history": get_history(limit=limit)})
    except Exception as exc:
        app.logger.warning("History read failed (%s)", type(exc).__name__)
        return api_error("Не удалось прочитать историю.", "history_unavailable", 500)


@app.route("/api/generated/<path:filename>")
def serve_generated(filename):
    if Path(filename).name != filename or Path(filename).suffix.lower() not in {".pdf", ".tex"}:
        return api_error("Файл не найден.", "file_not_found", 404)
    return send_from_directory(str(Path(latex_engine.OUTPUT_DIR).resolve()), filename)


if __name__ == "__main__":
    app.run(host="127.0.0.1", debug=False, port=3005)

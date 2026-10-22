"""Versioned worksheet data and deterministic, template-owned typesetting."""
from __future__ import annotations

import json
import re
import math
import hashlib
from pathlib import Path

from pypdf import PdfReader

from utils import latex
from utils.gigachat_client import AIServiceError, normalize_cyrillic_units

MAX_TASKS = 30


def invalid(message):
    raise AIServiceError(message, "invalid_worksheet", 400)


def text_field(value, name, limit, required=False):
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        invalid(f"{name}: требуется текст длиной до {limit} символов.")
    value = value.strip()
    if required and not value:
        invalid(f"Заполните поле «{name}».")
    return value


def validate_worksheet(value):
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        invalid("Неизвестный формат рабочего листа.")
    subject = value.get("subject", "math")
    if subject not in ("math", "physics"):
        invalid("Выберите математику или физику.")
    raw_tasks = value.get("tasks")
    if not isinstance(raw_tasks, list) or not 1 <= len(raw_tasks) <= MAX_TASKS:
        invalid(f"В листе должно быть от 1 до {MAX_TASKS} заданий.")
    tasks, ids = [], set()
    for i, task in enumerate(raw_tasks, 1):
        if not isinstance(task, dict):
            invalid("Неверный формат задания.")
        task_id = text_field(task.get("id", str(i)), "Номер задания", 64, True)
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", task_id) or task_id in ids:
            invalid("У заданий должны быть уникальные идентификаторы.")
        ids.add(task_id)
        item = {"id": task_id,
                "question": text_field(task.get("question"), f"Задание {i}", 4000, True),
                "answer": text_field(task.get("answer", ""), f"Ответ {i}", 2000),
                "note": text_field(task.get("note", ""), "Примечание", 500)}
        for field in ("question", "answer"):
            rich_text_to_tex(item[field])
        tasks.append(item)
    settings = value.get("settings", {})
    if not isinstance(settings, dict):
        invalid("Неверные настройки страницы.")
    columns, per_page = settings.get("columns", 1), settings.get("tasks_per_page", 3)
    if type(columns) is not int or columns not in (1, 2):
        invalid("Выберите 1 или 2 столбца.")
    if type(per_page) is not int or per_page not in range(1, 7):
        invalid("На странице можно разместить от 1 до 6 заданий.")
    field = settings.get("field", "grid")
    if field not in ("grid", "blank", "none"):
        invalid("Выберите клетку, пустое поле или список.")
    template = settings.get('template', 'cards')
    if template not in ('list', 'cards', 'guided', 'check'):
        invalid('Выберите шаблон рабочего листа.')
    print_sides = settings.get('print_sides', 'single')
    if print_sides not in ('single', 'duplex'):
        invalid('Выберите одностороннюю или двустороннюю печать.')
    variant = text_field(settings.get('variant', ''), 'Вариант', 12)
    lesson_date = text_field(settings.get('lesson_date', ''), 'Дата работы', 10)
    if lesson_date:
        from datetime import date
        try:
            if date.fromisoformat(lesson_date).isoformat() != lesson_date:
                raise ValueError()
        except ValueError:
            invalid('Укажите дату работы в формате ГГГГ-ММ-ДД.')
    return {"schema_version": 1, "subject": subject,
            "title": text_field(value.get("title", "Рабочий лист"), "Тема", 160, True),
            "teacher_name": text_field(value.get("teacher_name", ""), "Учитель", 120),
            "grade": text_field(value.get("grade", ""), "Класс", 20),
            "tasks": tasks,
            "settings": {"columns": columns, "tasks_per_page": per_page, "field": field,
                         "template": template, "print_sides": print_sides,
                         "variant": variant, "lesson_date": lesson_date}}


def edition_code(value):
    """Content-addressed edition, including answers and print settings (not a user ID)."""
    canonical = json.dumps(validate_worksheet(value), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode()).hexdigest()[:12].upper()


def rich_text_to_tex(text):
    """Escape all prose; accept a deliberately small math language inside $...$."""
    if text.count("$") % 2:
        invalid("В формуле не закрыт знак $. Исправьте формулу или уберите оба знака $.")
    result = []
    for i, part in enumerate(text.split("$")):
        if i % 2:
            if not part.strip():
                invalid("Пустая формула: используйте один знак $ с каждой стороны.")
            part = normalize_cyrillic_units(part)
            forbidden = {"TaskBox", "WriteField", "begin", "end", "newpage", "clearpage",
                         "pagebreak", "section", "subsection", "paragraph", "item", "color",
                         "textcolor", "rule", "hspace", "vspace", "hfill"}
            commands = set(re.findall(r"\\([A-Za-z@]+)", part))
            if commands - (latex._SAFE_COMMANDS - forbidden) or any(x in part for x in ("^^", "%", "#", "&", "\n", "\\\\")):
                invalid("Формула содержит неподдерживаемую команду или символ.")
            depth = 0
            for char in re.sub(r"\\[{}]", "", part):
                depth += (char == "{") - (char == "}")
                if depth < 0:
                    invalid("Проверьте скобки в формуле.")
            if depth:
                invalid("Проверьте скобки в формуле.")
            result.append("$" + part + "$")
        else:
            # Newlines become spaces, not user-controlled TeX commands.
            result.append(''.join(latex._ESCAPES.get(char, char) for char in part.replace('\n', ' ')))
    return "".join(result)


def parse_ai_worksheet(content, subject):
    if not isinstance(content, str) or len(content.encode("utf-8")) > 100_000:
        raise AIServiceError("ИИ вернул слишком большой или пустой ответ.", "ai_invalid_response", 502)
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    try:
        result = json.loads(content)
        if not isinstance(result, dict):
            raise ValueError("object required")
        result.update(schema_version=1, subject=subject)
        return validate_worksheet(result)
    except (ValueError, AIServiceError) as exc:
        raise AIServiceError("Не удалось разобрать задания в ответе ИИ. Попробуйте более чёткое фото или меньший фрагмент.",
                             "ai_invalid_response", 502) from exc


def worksheet_tex(data):
    settings, tasks = data["settings"], data["tasks"]
    count, columns = settings["tasks_per_page"], settings["columns"]
    # Conservative spacing leaves room for conditions. Overflow is rejected by compiler.
    rows = (count + columns - 1) // columns
    height = {1: 100, 2: 49, 3: 27, 4: 15, 5: 8, 6: 5}[rows]
    template = settings.get('template', 'cards')
    command = {'list': 'ListTask', 'cards': 'CardTask', 'guided': 'GuidedTask', 'check': 'CheckTask'}[template]
    field = rf'\WriteField{{{height}mm}}' if settings['field'] != 'none' else r'\vspace{2mm}'
    pages = []
    for offset in range(0, len(tasks), count):
        cells = []
        for index, task in enumerate(tasks[offset:offset + count], offset + 1):
            body = rf'\{command}{{{index}}}{{{rich_text_to_tex(task["question"])}}}{{{field}}}' + '\n'
            width = '0.48' if columns == 2 else '1'
            body = rf'\begin{{minipage}}[t]{{{width}\linewidth}}' + '\n\\vspace{0pt}\n' + body + '\\end{minipage}'
            if columns == 1:
                body += '\\par\n'
            cells.append(body)
        if columns == 2:
            rows_tex = [r"\hfill".join(cells[i:i + 2]) for i in range(0, len(cells), 2)]
            pages.append("\n\\par\\vspace{4mm}\n".join(rows_tex))
        else:
            pages.append("\n\\vspace{4mm}\n".join(cells))
    return "\n\\newpage\n\\ContinuationHeader\n".join(pages)


def compile_worksheet(value, base):
    data = validate_worksheet(value)
    body = worksheet_tex(data)
    answers = "\n".join(
        rf"\noindent\textbf{{{i}.}} {rich_text_to_tex(task['answer'] or 'Ответ не указан — требуется проверка.')}\par\vspace{{5mm}}"
        for i, task in enumerate(data["tasks"], 1))
    title = data['title']
    answers = r'\noindent\textbf{' + latex._escape_header(title) + '}\\par\\vspace{6mm}\n' + answers
    files = []
    for suffix, content, heading in (("", body, title), ("_keys", answers, 'Ответы для учителя')):
        pdf, error = latex._compile_single_doc(content, heading, base + suffix,
                                              data["teacher_name"], field_style=data["settings"]["field"],
                                              strict_layout=True, student_fields=not suffix,
                                              print_settings={**data['settings'], 'grade': data['grade'],
                                                              'code': edition_code(data), 'short_title': data['title']})
        if error:
            latex._remove_output(base)
            latex._remove_output(base + "_keys")
            raise AIServiceError(error, "latex_compile_failed", 422)
        files.append(pdf)
    expected_pages = math.ceil(len(data['tasks']) / data['settings']['tasks_per_page'])
    try:
        with (Path(latex.OUTPUT_DIR) / files[0]).open('rb') as stream:
            actual_pages = len(PdfReader(stream).pages)
        if actual_pages != expected_pages:
            raise ValueError('page overflow')
    except Exception as exc:
        latex._remove_output(base)
        latex._remove_output(base + '_keys')
        raise AIServiceError('Задания не поместились на выбранное число страниц. Уменьшите число заданий на странице или выберите один столбец.',
                             'layout_overflow', 422) from exc
    return files


DEMO_TASKS = {
    "math": ("Уравнения, дроби и корни", [
        (r"Решите уравнение $x^2-5x+6=0$.", r"$x_1=2$, $x_2=3$"),
        (r"Вычислите $\frac{3}{4}+\frac{5}{6}$. Ответ запишите несократимой дробью.", r"$\frac{19}{12}$"),
        (r"Вычислите $\sqrt{81}+\sqrt{16}$.", "$13$")]),
    "physics": ("Движение, сила тока и плотность", [
        (r"Тело движется с начальной скоростью $v_0=2\,\text{м/с}$ и ускорением $a=3\,\text{м/с}^2$. Найдите путь за $t=4\,\text{с}$ по формуле $s=v_0t+\frac{at^2}{2}$.", r"$32\,\text{м}$"),
        (r"Напряжение $U=12\,\text{В}$, сопротивление $R=4\,\text{Ом}$. Найдите силу тока по формуле $I=\frac{U}{R}$.", r"$3\,\text{А}$"),
        (r"Масса образца $m=540\,\text{г}$, объём $V=200\,\text{см}^3$. Найдите плотность $\rho=\frac{m}{V}$.", r"$2{,}7\,\text{г/см}^3$")])}


def demo_worksheet(subject):
    title, tasks = DEMO_TASKS[subject]
    return validate_worksheet({"schema_version": 1, "subject": subject, "title": title,
                               "tasks": [{"id": str(i), "question": q, "answer": a}
                                         for i, (q, a) in enumerate(tasks, 1)]})

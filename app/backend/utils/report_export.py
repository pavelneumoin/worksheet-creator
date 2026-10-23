"""Private teacher exports. Scores are official, typesetting is template-owned."""
import csv
from datetime import datetime, timedelta, timezone
import io
from pathlib import Path
import re

from pypdf import PdfReader
from utils import latex
from utils.gigachat_client import AIServiceError

LABELS = {'not_submitted': 'Не сдал', 'not_assigned': 'Не назначалась', 'processing': 'Распознаётся',
          'needs_review': 'Нужен учитель', 'failed': 'Ошибка распознавания', 'confirmed': 'Подтверждено'}


def csv_text(rows):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, delimiter=';')
    for row in rows:
        values = []
        for value in row:
            text = '' if value is None else str(value)
            if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')):
                text = "'" + text
            values.append(text)
        writer.writerow(values)
    return '\ufeff' + stream.getvalue()


def decimal(value):
    return None if value is None else str(value).replace('.', ',')


def assignment_csv(data):
    rows = [['Класс', 'Работа', 'Версия', 'Код ученика', 'Статус', 'Баллы', 'Максимум', 'Подтверждено',
             'Проведение', 'Сдать до', 'Черновик исправлений', 'Сформирован',
             *[f'Задание {i}' for i in range(1, len(data['tasks']) + 1)]]]
    for student in data['students']:
        rows.append([data['class_name'], data['title'], data['edition_code'], student['code'], LABELS[student['status']],
                     student['score'], student['maximum'], student['confirmed_at'], data['scheduled_date'], data['due_date'],
                     'Да' if student['has_draft'] else '', data['generated_at'], *student['task_scores']])
    return csv_text(rows)


def overview_csv(data):
    rows = [['Класс', 'Работа', 'Тема листа', 'Предмет', 'Версия', 'Состояние', 'Проведение', 'Сдать до',
             'Назначено ученикам', 'Получено', 'Подтверждено', 'Не сдано', 'Нужен учитель', 'Распознаются', 'Ошибки',
             'Максимум', 'Средний балл', 'Выполнение, %', 'Черновики исправлений',
             'Выбранный ученик', 'Статус ученика', 'Баллы ученика', 'Сформирован']]
    for work in data['works']:
        s, individual = work['summary'], work['student_result']
        rows.append([data['class_name'], work['title'], work['topic'], 'Физика' if work['subject'] == 'physics' else 'Математика',
                     work['edition_code'], 'Закрыта' if work['status'] == 'closed' else 'Назначена', work['scheduled_date'], work['due_date'],
                     s['total'], s['submitted'], s['confirmed'], s['not_submitted'], s['needs_review'], s['processing'], s['failed'],
                     s['maximum'], decimal(s['average']), decimal(s['percent']), s['pending_corrections'],
                     data['selected_student']['code'] if individual else '', LABELS[individual['status']] if individual else '',
                     individual['score'] if individual else None, data['generated_at']])
    return csv_text(rows)


def tex(value):
    # Escapes every user character; long unspaced names can wrap on A4 as well.
    value = ' '.join(str(value).split())
    result, run = [], 0
    for char in value:
        result.append(latex._ESCAPES.get(char, char))
        run = run + 1 if char.isalnum() else 0
        if run == 18:
            result.append(r'\allowbreak{}'); run = 0
    return ''.join(result)


def date_label(value):
    return '.'.join(reversed(value.split('-'))) if value else 'не указана'


def moscow_time(value):
    return datetime.fromisoformat(value).astimezone(timezone(timedelta(hours=3))).strftime('%d.%m.%Y %H:%M') + ' МСК'


def report_tex(data):
    s = data['summary']
    roster = []
    for student in data['students']:
        label = LABELS[student['status']] + (' *' if student['has_draft'] else '')
        roster.append(' & '.join([tex(student['code']), tex(label), str(student['score']) if student['score'] is not None else '-', str(student['maximum'])]) + r' \\')
    tasks = []
    for number, task in enumerate(data['tasks'], 1):
        tasks.append(' & '.join([str(number), str(task['correct']), str(task['total']),
                                tex(str(task['percent']).replace('.', ',')) + r'\%' if task['percent'] is not None else '-']) + r' \\')
    score = ('Пока нет подтверждённых результатов.' if s['average'] is None else
             f"Средний балл: {decimal(s['average'])} из {s['maximum']}. Выполнение: {decimal(s['percent'])}%.")
    template = (Path(__file__).resolve().parents[1] / 'templates/class_report.tex').read_text(encoding='utf-8')
    values = {'CLASS': tex(data['class_name']), 'TITLE': tex(data['title']), 'CODE': tex(data['edition_code']),
              'CREATED': tex(moscow_time(data['generated_at'])), 'SCHEDULED': tex(date_label(data['scheduled_date'])),
              'DUE': tex(date_label(data['due_date']) if data['due_date'] else 'не указан'), 'COUNTS': tex(f"Получено: {s['submitted']} из {s['total']}. Подтверждено: {s['confirmed']} из {s['total']}. Не сдано: {s['not_submitted']}."),
              'PENDING': tex(f"Нужен учитель: {s['needs_review']}. Распознаются: {s['processing']}. С ошибкой: {s['failed']}. Черновики исправлений: {s['pending_corrections']}."),
              'SCORE': tex(score), 'DENOMINATOR': tex(f"В расчёте только подтверждённые работы: {s['confirmed']} из {s['total']} назначенных учеников. Максимум за лист: {s['maximum']}."),
              'RECOMMENDATION': tex(data['recommendation']), 'ROSTER': '\n'.join(roster), 'TASKS': '\n'.join(tasks)}
    return re.sub(r'PLACEHOLDER:([A-Z]+)', lambda match: values[match.group(1)], template)


def compile_report(data, base):
    filename, error = latex.compile_latex_local(report_tex(data), base, strict_layout=True)
    if error:
        raise AIServiceError(error, 'report_compile_failed', 503)
    path = Path(latex.OUTPUT_DIR) / filename
    if not 1 <= len(PdfReader(path).pages) <= 20:
        raise AIServiceError('Отчёт оказался слишком большим. Проверьте данные класса.', 'report_page_limit', 400)
    return filename

"""Portable Marp sources with a bundled A4 theme; no AI or remote assets."""
import re
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from utils.worksheet import validate_worksheet

THEME_PATH = Path(__file__).resolve().parents[1] / 'templates/listok-marp.css'


def plain(text):
    # Escape Markdown/HTML syntax in prose. User text cannot create slides, links,
    # directives, images, comments or HTML, even with --html enabled for our layout.
    return re.sub(r'([!"#$%&\'()*+,\-./:;<=>?@\[\]\\^_`{|}~])', r'\\\1', re.sub(r'\s+', ' ', text))


def rich(text):
    return ''.join('$' + part + '$' if i % 2 else plain(part) for i, part in enumerate(text.split('$')))


def markdown(value, answers=False, origin=None):
    sheet = validate_worksheet(value)
    count, columns = sheet['settings']['tasks_per_page'], sheet['settings']['columns']
    if answers:
        count, columns = 6, 1
    rows = (count + columns - 1) // columns
    height = {1: 100, 2: 55, 3: 30, 4: 18, 5: 10, 6: 6}[rows]
    field = 'none' if answers else sheet['settings']['field']
    header = ('---\nmarp: true\ntheme: listok\nmath: katex\npaginate: true\n'
              f'class: columns-{columns} field-{field}\nstyle: |\n  section {{ --field-height: {height}mm; }}\n---\n\n')
    pages = []
    for offset in range(0, len(sheet['tasks']), count):
        page = ['# ' + ('Ответы для учителя' if answers else plain(sheet['title'])), '']
        if answers:
            page.extend(['## ' + plain(sheet['title']), ''])
        meta = ' · '.join(x for x in (sheet['grade'] + ' класс' if sheet['grade'] else '', sheet['teacher_name']) if x)
        if meta:
            page.extend(['<div class="meta">', '', plain(meta), '', '</div>', ''])
        if not answers:
            page.extend(['<div class="student">ФИО __________________________ Дата __________</div>', ''])
        page.extend(['<div class="task-grid">', ''])
        for i, task in enumerate(sheet['tasks'][offset:offset + count], offset + 1):
            content = task['answer'] or 'Ответ не указан — требуется проверка.' if answers else task['question']
            page.extend(['<div class="task">', '', f'**{i}.** {rich(content)}', ''])
            if not answers and field != 'none':
                page.extend(['<div class="answer-space"></div>', ''])
            page.extend(['</div>', ''])
        page.extend(['</div>', ''])
        if origin:
            page.extend(['<div class="attribution">', '', 'Основа: ' + plain(origin['author']) + ', «' + plain(origin['title']) + '».', '', '</div>', ''])
        pages.append('\n'.join(page))
    return header + '\n---\n\n'.join(pages)


def export_bundle(worksheet, destination, origin=None):
    destination = Path(destination)
    with ZipFile(destination, 'w', compression=ZIP_DEFLATED) as archive:
        archive.writestr('worksheet.md', markdown(worksheet, origin=origin))
        archive.writestr('answers.md', markdown(worksheet, answers=True, origin=origin))
        archive.writestr('listok.css', THEME_PATH.read_text(encoding='utf-8'))
        archive.writestr('README.txt',
            'ЛистОК — исходники Marp\n\n'
            'worksheet.md — задания, answers.md — отдельные ответы, listok.css — тема A4.\n'
            'Распакуйте весь архив в одну папку. Формулы редактируются между знаками $.\n'
            'Для Marp for VS Code добавьте listok.css в markdown.marp.themes и включите HTML.\n'
            'Проверенная командная строка (нужен Node.js):\n'
            'npx @marp-team/marp-cli@4.5.1 worksheet.md --theme listok.css --html --pdf\n'
            'npx @marp-team/marp-cli@4.5.1 answers.md --theme listok.css --html --pdf\n\n'
            'После редактирования проверьте страницы перед печатью.\n'
            'Для обычной печати используйте готовые PDF из ЛистОК.\n')
    return destination.name

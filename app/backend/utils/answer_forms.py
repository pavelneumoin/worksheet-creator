"""Compact answer-only sheets. One frozen assignment pupil per A4 page."""
from pathlib import Path

from pypdf import PdfReader
from utils import latex
from utils.report_export import tex, date_label
from utils.gigachat_client import AIServiceError


def form_tex(assignment, mode):
    if mode not in ('class', 'blank'):
        raise AIServiceError('Выберите бланк или комплект класса.', 'invalid_form_mode', 400)
    pupils = assignment['students'] if mode == 'class' else [{'code': ''}]
    pages = []
    for index, pupil in enumerate(pupils):
        code = tex(pupil['code']) if pupil['code'] else r'У-\rule{44mm}{0.3pt}'
        count = len(assignment['worksheet']['tasks'])
        rows = r'\begin{tikzpicture}[x=5.5mm,y=6mm]' + '\n'
        rows += rf'\draw[gridgray,line width=.3pt,xstep=1,ystep=1] (0,-{count}) grid (27,0);' + '\n'
        rows += '\n'.join(rf'\node[anchor=east,font=\small\bfseries] at (-.5,{-i + .5}) {{{i}}};' for i in range(1, count + 1))
        rows += '\n' + r'\end{tikzpicture}'
        marker = rf'\begin{{minipage}}[t]{{.18\textwidth}}\vspace{{0pt}}\includegraphics[width=\linewidth]{{qr_{index}.png}}\end{{minipage}}' if mode == 'class' else ''
        pages.append(rf'''
\begin{{minipage}}[t]{{.78\textwidth}}\vspace{{0pt}}
{{\small\bfseries ЛистОК / БЛАНК ОТВЕТОВ}}\par
\vspace{{3mm}}{{\large\bfseries\raggedright {tex(assignment['title'][:110])}\par}}
\vspace{{3mm}}\textbf{{Код ученика:}} {{\fontsize{{16}}{{19}}\selectfont\texttt{{{code}}}}}\par
\vspace{{2mm}}\textbf{{Версия работы:}} {{\fontsize{{14}}{{17}}\selectfont\texttt{{{tex(assignment['code'])}}}}}\par
\vspace{{2mm}}Класс: {tex(assignment['class_name'][:40])}\hfill Дата: {tex(date_label(assignment['scheduled_date']))}\par
\end{{minipage}}\hfill {marker}\par
\vspace{{3mm}}{{\small Один символ в клетке. Дробь: 3/4; несколько ответов: 2;3.\par
Если места мало, пишите свободно в строке. Решение — на рабочем листе.}}\par
\vspace{{3mm}}
{rows}
\vfill{{\footnotesize Для проверки сканируйте этот бланк целиком. Один ученик — одна страница.}}
''')
    template = (Path(__file__).resolve().parents[1] / 'templates/answer_form.tex').read_text(encoding='utf-8')
    return template.replace('PLACEHOLDER:CONTENT', '\n\\newpage\n'.join(pages))


def compile_forms(assignment, mode, base):
    from utils import answer_markers
    assets = {f'qr_{i}.png': answer_markers.png(assignment['id'], assignment['code'], pupil['code'])
              for i, pupil in enumerate(assignment['students'])} if mode == 'class' else {}
    filename, error = latex.compile_latex_local(form_tex(assignment, mode), base, strict_layout=True, assets=assets)
    if error:
        raise AIServiceError(error, 'answer_form_compile_failed', 422)
    expected = len(assignment['students']) if mode == 'class' else 1
    if len(PdfReader(Path(latex.OUTPUT_DIR) / filename).pages) != expected:
        latex._remove_output(base)
        raise AIServiceError('Бланк вышел за пределы страницы. Сократите название работы.', 'answer_form_overflow', 422)
    return filename

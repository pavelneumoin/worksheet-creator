"""Colour-coded, template-owned LaTeX exports, including detailed pupil codes."""
from pathlib import Path
from pypdf import PdfReader
from utils import latex,report_export
from utils.gigachat_client import AIServiceError

def percent(value):return '—' if value is None else str(value).replace('.',',')+'%'

def shade(value):
    return 'mutedbg' if value is None else 'redbg' if value<40 else 'amberbg' if value<70 else 'greenbg'

def table(headers,widths,rows):
    columns=''.join('p{'+str(w)+'mm}' for w in widths)
    header=' & '.join(r'\textbf{'+report_export.tex(h)+'}' for h in headers)+r' \\ \hline'
    return r'\begin{longtable}{@{}'+columns+r'@{}}\rowcolor{purplebg}'+header+r'\endfirsthead\rowcolor{purplebg}'+header+r'\endhead\hline\endfoot'+'\n'+'\n'.join(rows)+r'\end{longtable}'

def document(data):
    t=report_export.tex;s=data['totals']
    source=r'''\documentclass[a4paper,10pt]{article}
\usepackage{fontspec}
\setmainfont{cmun}[Path=fonts/,Extension=.otf,UprightFont=*rm,BoldFont=*bx,ItalicFont=*ti,BoldItalicFont=*bi]
\usepackage[russian]{babel}
\usepackage[a4paper,left=17mm,right=17mm,top=23mm,bottom=22mm,headheight=16pt]{geometry}
\usepackage{longtable,array,fancyhdr,lastpage,needspace}
\usepackage[table]{xcolor}
\definecolor{purple}{HTML}{7654D6}\definecolor{purplebg}{HTML}{F0EBFB}
\definecolor{greenbg}{HTML}{E8F4ED}\definecolor{amberbg}{HTML}{FFF3D8}\definecolor{redbg}{HTML}{FAE7E9}\definecolor{mutedbg}{HTML}{F4F4F7}
\setlength{\parindent}{0pt}\setlength{\emergencystretch}{3em}\setlength{\tabcolsep}{3pt}\renewcommand{\arraystretch}{1.35}
\pagestyle{fancy}\fancyhf{}\fancyhead[L]{\small\color{purple}ЛистОК / Аналитика обучения}\fancyfoot[R]{\small\thepage\ /\pageref{LastPage}}\renewcommand{\headrulewidth}{.3pt}
\raggedbottom\begin{document}
'''
    source+=r'{\Huge\bfseries\color{purple}'+t(data['title'])+r'}\par\vspace{4mm}'+'\n'
    source+=t('Сформирован '+report_export.moscow_time(data['generated_at']))+r'\par\medskip'+'\n'
    source+=t(f"Работ: {s['assignments']}. Классов: {s['classes']}. Учеников по кодам: {s['students']}.")+r'\par'+'\n'
    source+=t(f"Подтверждено {s['confirmed']} из {s['expected']} назначенных работ ({percent(s['coverage'])}). Выполнение заданий: {percent(s['percent'])}.")+r'\par\medskip'+'\n'
    source+=r'{\small '+t('Выполнение — сумма подтверждённых баллов, делённая на их максимум. Непроверенные и отсутствующие работы исключены. Это сводка разных заданий, а не рейтинг способностей учеников или учителей.')+r'}\par'+'\n'
    f=data['filters'];source+=t('Период: '+(f.get('from_date') or 'всё время')+' — '+(f.get('to_date') or 'без верхней границы')+'. Фильтр темы: '+(f.get('q') or 'все темы'))+r'\par'+'\n'
    source+=r'\section*{Классы}'
    rows=[r'\rowcolor{'+shade(c['percent'])+'}'+' & '.join(t(v) for v in [c['name'],f"{c['confirmed']} / {c['expected']}",percent(c['coverage']),percent(c['percent'])])+r' \\' for c in data['classes']]
    source+=table(['Класс','Подтверждено','Проверено','Выполнение'],[55,33,32,35],rows)
    source+=r'\subsection*{Выполнение заданий по классам}'
    for c in data['classes']:
        if c['percent'] is not None:
            source+=t(c['name'])+r'\quad '+t(percent(c['percent']))+r'\par{\color{purple}\rule{'+str(round(c['percent']*1.4,2))+r'mm}{2.2mm}}\par\medskip'
    source+=r'\section*{Темы: где нужна поддержка}'
    rows=[r'\rowcolor{'+shade(x['percent'])+'}'+' & '.join(t(v) for v in [x['topic'],x['confirmed'],percent(x['percent'])])+r' \\' for x in sorted(data['topics'],key=lambda x:(x['percent'] is None,x['percent'] or 0))]
    source+=table(['Тема','Работ','Выполнение'],[103,22,30],rows)
    source+=r'{\small '+t('Цветовые зоны: менее 40% — красная; 40–69,9% — жёлтая; от 70% — зелёная; без подтверждений — серая. Пороги служат ориентиром для повторения, а не школьными отметками.')+r'}\par'
    if data.get('insight'):
        source+=r'\section*{Рекомендации ИИ — для решения учителя}'
        for section in ('observations','actions'):
            for text in data['insight'].get(section,[]):source+=r'\noindent\textbullet\ '+t(text)+r'\par\smallskip'
    source+=r'\section*{По каждой работе}'
    rows=[' & '.join(t(v) for v in [w['class_name'],w['topic'],w['date'] or '—',f"{w['confirmed']}/{w['expected']}",percent(w['percent'])])+r' \\' for w in data['works']]
    source+=table(['Класс','Тема','Дата','Проверено','Выполнение'],[24,61,24,22,24],rows)
    source+=r'\section*{Задания для разбора}'
    rows=[r'\rowcolor{'+shade(r['percent'])+'}'+' & '.join(t(v) for v in [r['class_name'],r['topic'],r['number'],f"{r['correct']}/{r['confirmed']}",percent(r['percent'])])+r' \\' for r in data['tasks'] if r['percent'] is not None and r['percent']<70]
    source+=table(['Класс','Тема','№','Верно','Доля верных'],[24,61,16,25,29],rows) if rows else t('Подтверждённых затруднений ниже порога 70% не найдено.')+r'\par'
    source+=r'\section*{Подробные результаты по кодам}'
    rows=[]
    for r in data['students']:
        p=100*r['score']/r['maximum'] if r['score'] is not None else None
        rows.append(r'\rowcolor{'+shade(p)+'}'+' & '.join(t(v) for v in [r['class_name'],r['student_code'],r['topic'],report_export.LABELS[r['status']],f"{r['score']}/{r['maximum']}" if r['score'] is not None else '—'])+r' \\')
    source+=table(['Класс','Код ученика','Тема','Статус','Баллы'],[22,33,48,32,20],rows)
    source=source.replace(r'\section*',r'\Needspace{45mm}\section*').replace(r'\subsection*',r'\Needspace{30mm}\subsection*')
    return source+r'\end{document}'

def compile_report(data,base):
    filename,error=latex.compile_latex_local(document(data),base,strict_layout=True)
    if error:raise AIServiceError(error,'analytics_pdf_failed',422)
    if len(PdfReader(Path(latex.OUTPUT_DIR)/filename).pages)>150:raise AIServiceError('Сузьте период: отчёт превышает 150 страниц.','report_limit',400)
    return filename

"""Opt-in live provider check using only a synthetic typed solution, never pupil data."""
import json
import os
from pathlib import Path
import sys
import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--live',action='store_true',help='Send the synthetic example to the configured provider (uses API quota).')
if not parser.parse_args().live:parser.error('Pass --live to use the configured API quota.')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app/backend'))
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')
base=ROOT/'output/solution-live';base.mkdir(parents=True,exist_ok=True)
os.environ['LISTOK_DB_PATH']=str(base/'checks.db')
os.environ['LISTOK_GENERATED_DIR']=str(base)
from utils import db,latex,source_pages,solution_ai
db.init_db();latex.OUTPUT_DIR=str(base)
source=r'''\documentclass[a4paper,12pt]{article}
\usepackage{fontspec}\setmainfont{cmun}[Path=fonts/,Extension=.otf,UprightFont=*rm,BoldFont=*bx,ItalicFont=*ti,BoldItalicFont=*bi]
\usepackage[russian]{babel}\usepackage{amsmath,amssymb}\usepackage[margin=22mm]{geometry}
\begin{document}\section*{Учебная работа — синтетический пример}
\subsection*{Задание 1}
$2\sin^2 x-3\sin x+1=0$. Пусть $t=\sin x$. Тогда $(2t-1)(t-1)=0$.
$\sin x=1/2$ или $\sin x=1$.
Ответ: $x=\pi/6+2\pi n$, $x=5\pi/6+2\pi n$, $x=\pi/2+2\pi n$, $n\in\mathbb Z$.
На отрезке $[0;2\pi]$: $\pi/6$, $\pi/2$, $5\pi/6$.
\subsection*{Задание 2}
$\log_2(x-1)+\log_2(x-3)=3$.
$\log_2((x-1)(x-3))=3$. Значит, $x^2-4x+3=8$.
$x^2-4x-5=0$. Корни $x=-1$ и $x=5$.
Ответ: $-1;5$.
\end{document}'''
filename,error=latex.compile_latex_local(source,'synthetic-solution',strict_layout=True)
if error:raise RuntimeError(error)
paths=source_pages.prepare([base/filename],base/'pages')
tasks=[{'id':'1','question':r'Решите $2\sin^2x-3\sin x+1=0$ и отберите корни на $[0;2\pi]$.','answer':r'$\pi/6+2\pi n;5\pi/6+2\pi n;\pi/2+2\pi n$. На отрезке $\pi/6;\pi/2;5\pi/6$.'},
       {'id':'2','question':r'Решите $\log_2(x-1)+\log_2(x-3)=3$.','answer':'$x=5$, ОДЗ $x>3$.'}]
result=solution_ai.analyze(tasks,paths)
(base/'analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
assert len(result['tasks'])==2
for row in result['tasks']:
    print(row['task_id'],row['suggested_score'],row['uncertain'],row['reason'],flush=True)
print('Live analysis saved; teacher confirmation still required.',flush=True)

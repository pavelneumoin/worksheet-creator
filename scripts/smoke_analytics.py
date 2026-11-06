"""Compile the actual school report template without network or provider credentials."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app/backend'))
from utils import analytics_export,latex
from pypdf import PdfReader

def main():
    data={'title':'Учебная школа · проверка экспорта','generated_at':'2026-11-06T12:00:00+00:00','filters':{},
          'totals':{'assignments':1,'classes':1,'students':2,'confirmed':1,'expected':2,'coverage':50.0,'percent':66.7},
          'classes':[{'name':'8А','confirmed':1,'expected':2,'coverage':50.0,'percent':66.7}],
          'topics':[{'topic':'Обыкновенные дроби','confirmed':1,'percent':66.7}],
          'works':[{'class_name':'8А','topic':'Обыкновенные дроби','date':'2026-11-06','confirmed':1,'expected':2,'percent':66.7}],
          'tasks':[{'class_name':'8А','topic':'Обыкновенные дроби','number':2,'correct':0,'confirmed':1,'percent':0}],
          'students':[{'class_name':'8А','student_code':'У-ABCDEF1234','topic':'Обыкновенные дроби','status':'confirmed','score':2,'maximum':3},
                      {'class_name':'8А','student_code':'У-123456ABCD','topic':'Обыкновенные дроби','status':'not_submitted','score':None,'maximum':3}],
          'insight':{'observations':['Проверена одна из двух работ.'],'actions':['Обсудить сложение дробей.']}}
    name=analytics_export.compile_report(data,'smoke_school_report')
    pdf=PdfReader(Path(latex.OUTPUT_DIR)/name)
    text='\n'.join(p.extract_text() for p in pdf.pages)
    assert 1<=len(pdf.pages)<=3 and 'У-ABCDEF1234' in text and 'Обсудить сложение дробей.' in text
    print('School PDF: real colour tables, charts, Cyrillic, recommendations and pupil codes OK')

if __name__=='__main__':main()

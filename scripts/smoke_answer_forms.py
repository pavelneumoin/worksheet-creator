"""Real A4 typesetting: 3/30 tasks, escaped long titles and a full class pack."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))
from utils.answer_forms import compile_forms
from utils.worksheet import demo_worksheet
from utils import latex
from pypdf import PdfReader
import pypdfium2 as pdfium
from utils import answer_markers

sheet = demo_worksheet('math')
assignment = {'id': 'a' * 32, 'worksheet': sheet, 'title': 'Уравнения, дроби и корни', 'class_name': '8А',
              'code': 'EF9582CCD530', 'scheduled_date': '2026-11-06',
              'students': [{'code': 'У-0123456789'}, {'code': 'У-ABCDEF1234'}]}
for count, mode in ((3, 'blank'), (3, 'class'), (30, 'blank'), (30, 'class')):
    sheet['tasks'] = [{'id': str(i), 'question': 'Вычислите.', 'answer': 'PRIVATE-ANSWER'} for i in range(1, count + 1)]
    assignment['title'] = ('Проверка & повторение: ' + 'длинноеназваниебезпробелов' * 5) if count == 30 else 'Уравнения, дроби и корни'
    name = compile_forms(assignment, mode, f'answer_form_{count}_{mode}')
    reader = PdfReader(Path(latex.OUTPUT_DIR) / name)
    assert len(reader.pages) == (2 if mode == 'class' else 1)
    text = '\n'.join(page.extract_text() for page in reader.pages)
    assert 'PRIVATE-ANSWER' not in text
    assert 'EF9582CCD530' in text
    if mode == 'class':
        with pdfium.PdfDocument(str(Path(latex.OUTPUT_DIR) / name)) as document:
            for i in range(len(document)):
                scan = Path(latex.OUTPUT_DIR) / f'form_qr_scan_{i}.jpg'
                document[i].render(scale=2).to_pil().convert('RGB').save(scan, quality=85)
                marker = answer_markers.read(scan)
                assert marker['student_code'] == assignment['students'][i]['code'], marker
                assert marker['assignment_code'] == assignment['id'], marker
    print(f'PASS {name}: {len(reader.pages)} A4 pages, {count} tasks')
assignment['title'] = 'Комплект класса: 30 учеников, 30 заданий'
assignment['students'] = [{'code': f'У-{i:010X}'} for i in range(30)]
name = compile_forms(assignment, 'class', 'answer_form_full_class')
assert len(PdfReader(Path(latex.OUTPUT_DIR) / name).pages) == 30
print('PASS full class: exactly 30 pupil pages')

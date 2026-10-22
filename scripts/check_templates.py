"""Real, offline CMU/headers/pagination check plus a printable template catalogue."""
from copy import deepcopy
from pathlib import Path
import sys
from pypdf import PdfReader, PdfWriter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))
from utils import latex
from utils.worksheet import demo_worksheet, compile_worksheet, edition_code


def main():
    output = ROOT / 'output/pdf'
    output.mkdir(parents=True, exist_ok=True)
    latex.OUTPUT_DIR = str(output)
    catalogue = PdfWriter()
    names = {'list':'Компактный', 'cards':'Карточки', 'guided':'По шагам', 'check':'С проверкой'}
    for template, label in names.items():
        for columns in (1, 2):
            sheet = demo_worksheet('physics' if template == 'guided' else 'math')
            sheet['teacher_name'] = 'Николай Семченков'
            sheet['grade'] = '8А'
            sheet['tasks'].append(dict(sheet['tasks'][0], id='4'))
            sheet['settings'].update(template=template, columns=columns, tasks_per_page=2,
                                     variant='1', lesson_date='2026-10-23', print_sides='duplex')
            files = compile_worksheet(sheet, f'template_{template}_{columns}')
            code = edition_code(sheet)
            for name in files:
                reader = PdfReader(output / name)
                for i, page in enumerate(reader.pages, 1):
                    text = page.extract_text()
                    assert code in text, (name, 'missing edition code')
                    assert '?' not in text, (name, 'unresolved page total')
                    assert f'{i} / {len(reader.pages)}' in ' '.join(text.split()), (name, 'page total')
                    fonts = page['/Resources']['/Font']
                    assert any('CMUSerif' in str(font.get_object().get('/BaseFont')) for font in fonts.values()), name
                assert len(reader.pages) == (2 if '_keys' not in name else 1), name
            if columns == 1:
                catalogue.append(str(output / files[0]), outline_item=label)
            print(f'{template}, {columns} col: PDF, answers, CMU, edition code and page totals OK', flush=True)
    catalogue.write(output / 'listok-template-catalogue.pdf')
    catalogue.close()


if __name__ == '__main__': main()

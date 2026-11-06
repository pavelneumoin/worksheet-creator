"""Real CMU + Computer Modern math specimens, with pagination and glyph checks."""
from pathlib import Path
import sys
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))
from utils import latex
from utils.worksheet import demo_worksheet, compile_worksheet


def main():
    output = ROOT / 'output/pdf'; output.mkdir(parents=True, exist_ok=True)
    latex.OUTPUT_DIR = str(output)
    sheet = demo_worksheet('math')
    sheet.update(title='Математика: уравнения, дроби и корни',grade='8А')
    sheet['settings'].update(template='cards', columns=1, tasks_per_page=3, field_height_mm=20)
    samples = [
        (r'Решите уравнение $x^{2}-5x+6=0$.',r'$x_{1}=2$, $x_{2}=3$'),
        (r'Вычислите $\frac{3}{4}+\frac{5}{6}$. Ответ запишите несократимой дробью.',r'$\frac{19}{12}$'),
        (r'Упростите выражение $\sqrt{50}-2\sqrt{8}$.',r'$\sqrt{2}$'),
        (r'Решите систему $\begin{cases}x+y=3,\\x-y=1.\end{cases}$',r'$x=2$, $y=1$'),
        (r'Вычислите $\log_{2}8+\sin\left(\frac{\pi}{6}\right)$.',r'$\frac{7}{2}$'),
        (r'Тело массой $m=2,5\,кг$ движется с ускорением $a=3\,м/с^{2}$. Найдите силу $F=ma$.',r'$F=7,5\,Н$'),
    ]
    sheet['tasks'] = [dict(id=str(i),question=q,answer=a,note='') for i,(q,a) in enumerate(samples,1)]
    for name in compile_worksheet(sheet,'listok-cmu-math'):
        reader = PdfReader(output/name)
        fonts = {str(f.get_object().get('/BaseFont')) for page in reader.pages for f in page['/Resources']['/Font'].values()}
        assert any('CMUSerif' in f for f in fonts), fonts
        assert any('CMMI' in f or 'CMSY' in f for f in fonts), fonts
        assert len(reader.pages) == (1 if '_keys' in name else 2)
        print(name, 'CMU text, Computer Modern math, page count and strict layout OK', flush=True)


if __name__ == '__main__': main()

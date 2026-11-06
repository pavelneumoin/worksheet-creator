"""Build the checked CMU PDFs shipped with the demo; never runs during a request."""
from pathlib import Path
import sys, shutil
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app/backend'))
from utils import latex
from utils.demo_catalog import sheets
from utils.worksheet import compile_worksheet
from pypdf import PdfReader,PdfWriter
from PIL import Image,ImageDraw,ImageFont
import pypdfium2

out=ROOT/'output/pdf/demo';out.mkdir(parents=True,exist_ok=True)
dest=ROOT/'app/backend/assets/demo';dest.mkdir(parents=True,exist_ok=True)
latex.OUTPUT_DIR=str(out)
for key,sheet in sheets().items():
    names=compile_worksheet(sheet,'demo_'+key)
    writer=PdfWriter()
    for name in names:
        reader=PdfReader(out/name)
        assert len(reader.pages)==1
        writer.append(reader)
        shutil.copyfile(out/name,dest/(key+('_keys' if '_keys' in name else '')+'.pdf'))
    with (dest/(key+'_teacher.pdf')).open('wb') as f:writer.write(f)
    doc=pypdfium2.PdfDocument(str(out/names[0]));page=doc[0];bitmap=page.render(scale=1.7)
    bitmap.to_pil().save(dest/(key+'.png'));bitmap.close();page.close();doc.close()
    print(key,'PDF, answers, teacher bundle, input image ready',flush=True)
font=ImageFont.truetype(str(ROOT/'app/backend/assets/fonts/cmu/cmunrm.otf'),38)
image=Image.new('RGB',(1100,1400),'white');draw=ImageDraw.Draw(image)
for i,text in enumerate(['ДЕМО / Список учеников 6А','Все имена вымышлены','',
    '1. Лебедева Анна','2. Соколов Михаил','3. Орлова Мария','4. Волков Артём',
    '5. Морозова Елена','6. Новиков Илья','7. Васильева Софья','8. Зайцев Тимофей']):
    draw.text((70,70+i*95),text,font=font,fill='#202a3d')
image.save(dest/'roster.png')

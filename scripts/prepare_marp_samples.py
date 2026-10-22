"""Create representative exported sources for render checks (no AI needed)."""
from pathlib import Path
import sys
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app/backend'))
from utils.worksheet import demo_worksheet
from utils.marp_export import export_bundle

output=ROOT/'output/qa/marp'
output.mkdir(parents=True,exist_ok=True)
for subject,columns,count,field in [('math',1,3,'grid'),('physics',1,3,'grid'),('math',2,2,'blank'),('math',2,6,'none')]:
    sheet=demo_worksheet(subject)
    sheet['settings']={'columns':columns,'tasks_per_page':count,'field':field}
    sheet['grade']='8';sheet['teacher_name']='ЛатехТим'
    name=f'{subject}_{columns}_{count}_{field}'
    archive=output/(name+'.zip')
    export_bundle(sheet,archive)
    with ZipFile(archive) as package:
        package.extractall(output/name)  # only our four fixed, generated member names
print('Prepared 4 Marp cases in output/qa/marp')

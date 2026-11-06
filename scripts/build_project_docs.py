"""Build the printable project documentation from the repository root."""
from pathlib import Path
import shutil
import subprocess
import os
ROOT=Path(__file__).resolve().parents[1]
engine=shutil.which('xelatex')
if not engine:
    candidate=Path(os.environ.get('LOCALAPPDATA',''))/'Programs/MiKTeX/miktex/bin/x64/xelatex.exe'
    if candidate.is_file():engine=str(candidate)
if not engine:raise SystemExit('Install XeLaTeX first.')
build=ROOT/'output/pdf/project-build';build.mkdir(parents=True,exist_ok=True)
for _ in range(2):
    run=subprocess.run([engine,'-interaction=nonstopmode','-halt-on-error','-no-shell-escape',
        '-output-directory='+str(build),'docs/project/listok-project.tex'],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (build/'build-console.txt').write_bytes(run.stdout)
    if run.returncode:raise SystemExit('XeLaTeX failed; see '+str(build/'build-console.txt'))
log=(build/'listok-project.log').read_text(encoding='utf-8',errors='replace')
if 'Overfull \\hbox' in log or 'Overfull \\vbox' in log:raise SystemExit('Layout overflow; inspect the TeX log.')
for target in (ROOT/'docs/project/listok-project.pdf',ROOT/'output/pdf/listok-project.pdf'):
    shutil.copyfile(build/'listok-project.pdf',target)
print('Project PDF ready:',ROOT/'docs/project/listok-project.pdf')

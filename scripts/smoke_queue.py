"""Real isolated job -> worker process -> PDFs + Marp, no network or AI required."""
import os
from pathlib import Path
import sys
import tempfile
import uuid
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))


def main():
    with tempfile.TemporaryDirectory(prefix='listok-queue-smoke-') as directory:
        os.environ['LISTOK_DB_PATH'] = str(Path(directory)/'queue.db')
        os.environ['LISTOK_JOBS_DIR'] = str(Path(directory)/'jobs')
        os.environ['LISTOK_GENERATED_DIR'] = str(Path(directory)/'generated')
        from utils import db, job_store, job_runner, workspace_store, class_store
        from utils.worksheet import demo_worksheet
        db.init_db()
        with workspace_store.connection() as conn:
            conn.execute("INSERT INTO users VALUES ('smoke','Smoke teacher','local')")
        sheet = demo_worksheet('math')
        material = workspace_store.put_material('smoke', sheet, 'manual_demo')
        payload = {'worksheet':sheet,'material_id':material['id'],'revision':material['revision']}
        key = uuid.uuid4().hex
        job, created = job_store.submit('smoke','compile',key,payload,require_worker=False)
        assert created
        duplicate, created = job_store.submit('smoke','compile',key,payload,require_worker=False)
        assert not created and duplicate['id']==job['id']
        db.init_db()  # process restart does not discard the queued job
        job_runner.run_one('compile','smoke-worker')
        result = job_store.get_job('smoke',job['id'])
        assert result['status']=='succeeded', result
        assert result['result']['attached']
        for key in ('pdf_url','keys_url'):
            path = Path(directory)/'generated'/result['result'][key].rsplit('/',1)[-1]
            assert path.read_bytes().startswith(b'%PDF-')
        archive = Path(directory)/'generated'/result['result']['marp_url'].rsplit('/',1)[-1]
        with ZipFile(archive) as package:
            assert {'worksheet.md','answers.md','listok.css','README.txt'}==set(package.namelist())
        assert not job_store.job_directory(job['id']).exists()
        classroom = class_store.create_class('smoke', {'name':'Report smoke'})
        classroom = class_store.add_students('smoke', classroom['id'], {'revision':classroom['revision'],'count':2})
        assignment, _ = class_store.assign('smoke', classroom['id'], {'revision':classroom['revision'],'edition_id':job['id'],
            'title':'Private report smoke','request_key':uuid.uuid4().hex})
        export, _ = job_store.submit('smoke','report_pdf',uuid.uuid4().hex,{'assignment_id':assignment['id']},require_worker=False)
        job_runner.run_one('compile','smoke-worker')
        export = job_store.get_job('smoke',export['id'])
        assert export['status']=='succeeded', export
        report_path = Path(directory)/'generated'/export['result']['pdf_url'].rsplit('/',1)[-1]
        from pypdf import PdfReader
        text = '\n'.join(page.extract_text() or '' for page in PdfReader(report_path).pages)
        assert 'Private report smoke' in text and 'Прочерк означает' in text and classroom['students'][0]['code'] in text
        assert workspace_store.owns_file('smoke',report_path.name)
        assert not workspace_store.owns_file('other',report_path.name)
        assert not job_store.job_directory(export['id']).exists()
        print('PASS: persistent queue, worker, PDF/answers/TeX/Marp, private report PDF without AI, coded roster, cleanup')


if __name__=='__main__': main()

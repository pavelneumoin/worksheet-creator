"""A saved recognition becomes printable without a second browser request."""
import json
from pathlib import Path
import unittest
import uuid
import test_personal as personal
import test_cabinet_storage as cabinet
from utils.gigachat_client import AIServiceError
from utils import job_store,workspace_store,backup
from utils.worksheet import demo_worksheet


class TeacherFlowTests(unittest.TestCase):
    setUp=personal.PersonalTests.setUp
    call=personal.PersonalTests.call
    signed=personal.PersonalTests.signed
    login=personal.PersonalTests.login
    create=personal.PersonalTests.create
    compiled=cabinet.CabinetTests.compiled

    def test_old_edition_gets_private_answer_form_without_recompiling_sheet(self):
        _,edition=self.compiled()
        with self.assertRaises(AIServiceError):
            job_store.submit('max:22','material_form',uuid.uuid4().hex,{'edition_id':edition},require_worker=False)
        job,_=job_store.submit('max:11','material_form',uuid.uuid4().hex,{'edition_id':edition},require_worker=False)
        claim=job_store.claim_next('compile');base='job_'+job['id']
        Path(self.temp.name,base+'.pdf').write_bytes(b'%PDF-fixture')
        Path(self.temp.name,base+'.tex').write_text('fixture')
        self.assertTrue(job_store.complete(claim,{}))
        with workspace_store.connection() as conn:
            row=conn.execute('SELECT pdf,answer_form FROM artifacts WHERE id=?',(edition,)).fetchone()
            self.assertEqual(row['pdf'],'job_'+edition+'.pdf')
            self.assertEqual(row['answer_form'],base+'.pdf')
            self.assertIn(base+'.pdf',backup.artifact_names(conn))
        self.assertFalse(workspace_store.owns_file('max:22',base+'.pdf'))

    def preview(self,count=1):
        job,_=job_store.submit('max:11','recognize',uuid.uuid4().hex,
            {'subject':'math','text':'sample','variant_count':count,'auto_compile':True},require_worker=False)
        claimed=job_store.claim_next('ai')
        sheets=[demo_worksheet('math') for _ in range(count)]
        for i,w in enumerate(sheets):w['title']+=' '+str(i+1)
        self.assertTrue(job_store.complete(claimed,{'worksheets':sheets}))
        return claimed,job_store.get_job('max:11',job['id'])

    def test_preview_chain_is_persistent_frozen_and_completed_once(self):
        claim,parent=self.preview(2)
        ids=[m['compile_job_id'] for m in parent['result']['materials']]
        self.assertEqual(len(set(ids)),2)
        self.assertFalse(job_store.complete(claim,{'worksheets':[demo_worksheet('math')]}))
        with workspace_store.connection() as c:
            rows=c.execute("SELECT * FROM jobs WHERE kind='compile'").fetchall()
            self.assertEqual(len(rows),2)
            for r in rows:
                p=json.loads(r['payload'])
                self.assertTrue(p['auto_preview']);self.assertEqual(p['revision'],1)
                self.assertEqual(r['status'],'queued');self.assertEqual(r['owner_id'],'max:11')
        self.assertEqual(job_store.claim_next('compile')['id'],ids[0])
        self.assertEqual(self.call(self.other,'get','/api/v2/jobs/'+ids[0]).status_code,404)

    def test_preview_does_not_overwrite_edits_and_answer_form_is_private_backed_up(self):
        _,parent=self.preview()
        material=parent['result']['materials'][0];claim=job_store.claim_next('compile')
        with workspace_store.connection() as c:
            c.execute('UPDATE materials SET revision=revision+1 WHERE id=?',(material['material_id'],))
        base='job_'+claim['id']
        for suffix in ('.pdf','_keys.pdf','_answer_form.pdf'):
            Path(self.temp.name,base+suffix).write_bytes(b'%PDF-fixture')
        Path(self.temp.name,base+'.tex').write_text('fixture')
        Path(self.temp.name,base+'_marp.zip').write_bytes(b'fixture')
        self.assertTrue(job_store.complete(claim,{'ok':True}))
        result=job_store.get_job('max:11',claim['id'])['result']
        self.assertFalse(result['attached']);self.assertIsNone(result['material_id'])
        name=base+'_answer_form.pdf'
        self.assertTrue(workspace_store.owns_file('max:11',name))
        self.assertFalse(workspace_store.owns_file('max:22',name))
        self.assertEqual(self.call(self.other,'get',result['answer_form_url']).status_code,404)
        with workspace_store.connection() as c:
            self.assertIn(name,backup.artifact_names(c))


if __name__=='__main__':unittest.main()

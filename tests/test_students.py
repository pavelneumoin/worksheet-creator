"""Student/teacher boundary, corrections, idempotency and private file backups."""
from contextlib import closing
import io
import json
from pathlib import Path
import time
import unittest
import uuid
from unittest.mock import patch
from PIL import Image
import test_reviews as reviews
from utils import backup, job_store, review_store, student_store, workspace_store
from utils.gigachat_client import AIServiceError


class StudentTests(unittest.TestCase):
    setUp=reviews.ReviewTests.setUp
    call=reviews.ReviewTests.call
    signed=reviews.ReviewTests.signed
    login=reviews.ReviewTests.login
    create=reviews.ReviewTests.create
    compiled=reviews.ReviewTests.compiled
    classroom=reviews.ReviewTests.classroom
    assignment=reviews.ReviewTests.assignment
    photo=reviews.ReviewTests.photo

    def joined(self):
        c,_,a,_=self.assignment()
        invite=student_store.invite('max:11',a['students'][0]['id'])
        response=self.call(self.other,'post','/api/v2/student/join',json={'token':invite['token']})
        self.assertEqual(response.status_code,200,response.json)
        return c,a,invite

    def uploaded(self,a,key=None):
        data=io.BytesIO();Image.new('RGB',(90,90),'white').save(data,'JPEG');data.seek(0)
        response=self.call(self.other,'post',f"/api/v2/student/assignments/{a['id']}/attempts",data={'files':(data,'work.jpg')},headers={'Idempotency-Key':key or uuid.uuid4().hex})
        self.assertIn(response.status_code,(200,201),response.json)
        return response.json['attempt']

    def confirm(self,attempt,score=.5):
        data=student_store.inbox('max:11')
        a=next(x for x in data if x['id']==attempt['id'])
        value={'action':'confirm','revision':a['revision'],'reviewed':True,'comment':'Проверьте преобразование.',
               'answers':[{'task_id':t['id'],'text':'test','score':score,'comment':'Пропущено обоснование.'} for t in a['tasks']]}
        return student_store.update('max:11',a['id'],value)

    def test_invitation_is_one_use_rotates_and_binds_real_account(self):
        c,a,invite=self.joined()
        self.assertEqual(self.call(self.other,'post','/api/v2/student/join',json={'token':invite['token']}).status_code,404)
        self.assertEqual(self.call(self.other,'post',f"/api/v2/students/{a['students'][1]['id']}/invite").status_code,404)
        self.assertEqual(self.call(self.anon,'get','/api/v2/student/assignments').status_code,401)
        student_store.revoke('max:11',a['students'][0]['id'])
        old=student_store.invite('max:11',a['students'][0]['id'])
        new=student_store.invite('max:11',a['students'][0]['id'])
        with self.assertRaises(AIServiceError):student_store.claim('max:22',{'token':old['token']})
        with workspace_store.connection() as conn:conn.execute('UPDATE student_invites SET expires_at=?',(time.time()-1,))
        with self.assertRaises(AIServiceError):student_store.claim('max:22',{'token':new['token']})

    def test_pupil_gets_only_own_questions_without_keys_or_teacher_routes(self):
        c,a,_=self.joined()
        response=self.call(self.other,'get',f"/api/v2/student/assignments/{a['id']}")
        self.assertEqual(response.status_code,200,response.json)
        detail=response.json['assignment']
        self.assertTrue(all(set(t)=={'id','question'} for t in detail['tasks']))
        self.assertNotIn('students',detail)
        self.assertNotIn('keys_url',json.dumps(detail))
        with self.call(self.other,'get',detail['pdf_url']) as response:self.assertEqual(response.status_code,200)
        self.assertEqual(self.call(self.other,'get',a['result']['keys_url']).status_code,404)
        self.assertEqual(self.call(self.other,'get','/api/v2/assignments/'+a['id']).status_code,404)
        self.assertEqual(self.call(self.client,'get','/api/v2/student/assignments/'+a['id']).status_code,404)

    def test_submit_retry_no_duplicate_other_pupil_and_revocation(self):
        c,a,_=self.joined();key=uuid.uuid4().hex;attempt=self.uploaded(a,key)
        self.assertEqual(self.uploaded(a,key)['id'],attempt['id'])
        self.assertEqual(self.call(self.client,'get','/api/v2/student-attempts').json['attempts'][0]['id'],attempt['id'])
        self.assertEqual(self.call(self.other,'get','/api/v2/student-attempts').json['attempts'],[])
        report=review_store.report('max:11',a['id'])
        self.assertEqual(report['summary']['needs_review'],1)
        self.assertEqual(report['summary']['confirmed'],0)
        self.assertEqual(report['students'][0]['student_attempt_id'],attempt['id'])
        self.login(self.anon,33)
        self.assertEqual(self.call(self.anon,'get',attempt['files'][0]['url']).status_code,404)
        self.assertEqual(self.call(self.anon,'get','/api/v2/student-attempts/'+attempt['id']).status_code,404)
        self.assertEqual(self.call(self.other,'put','/api/v2/student-attempts/'+attempt['id'],json={'action':'confirm'}).status_code,404)
        student_store.revoke('max:11',a['students'][0]['id'])
        self.assertEqual(self.call(self.other,'get',attempt['files'][0]['url']).status_code,404)
        with self.call(self.client,'get',attempt['files'][0]['url']) as response:self.assertEqual(response.status_code,200)

    def test_corrected_attempt_preserves_old_grade_until_confirmation(self):
        _,a,_=self.joined();attempt=self.uploaded(a);confirmed=self.confirm(attempt,.25)
        old=review_store.report('max:11',a['id'])['summary']['average']
        returned=student_store.update('max:11',attempt['id'],{'revision':confirmed['revision'],'action':'return','feedback':'Добавьте ОДЗ.'})
        corrected=self.uploaded(a)
        self.assertEqual(corrected['number'],2)
        self.assertEqual(review_store.report('max:11',a['id'])['summary']['average'],old)
        self.assertEqual(review_store.report('max:11',a['id'])['summary']['pending_corrections'],1)
        with workspace_store.connection() as conn:detail=student_store.student_assignment(conn,'max:22',a['id'])
        self.assertEqual(detail['result']['score'],old)
        confirmed2=self.confirm(corrected,1)
        self.assertEqual(review_store.report('max:11',a['id'])['summary']['average'],len(a['worksheet']['tasks']))
        with workspace_store.connection() as conn:
            row=conn.execute('SELECT id FROM reviews WHERE assignment_id=?',(a['id'],)).fetchone()
            self.assertEqual(conn.execute('SELECT count(*) FROM review_history WHERE review_id=?',(row['id'],)).fetchone()[0],2)
        self.assertEqual(returned['status'],'returned')
        with self.assertRaises(AIServiceError):self.confirm(attempt)

    def test_queue_failure_retry_and_stale_worker_fencing(self):
        _,a,_=self.joined();attempt=self.uploaded(a)
        path=student_store.folder(attempt['id'])/'0.jpg'
        job,_=job_store.submit('max:11','student_grade',uuid.uuid4().hex,{'attempt_id':attempt['id'],'revision':1},[path],require_worker=False)
        claim=job_store.claim_next('ai');directory=job_store.job_directory(job['id'])/'pages';directory.mkdir();Image.new('RGB',(90,90),'white').save(directory/'page_1.jpg')
        output={'answers':[{'task_id':t['id'],'text':t['answer'],'state':'readable'} for t in a['worksheet']['tasks']],'photos':['page_1.jpg']}
        self.assertTrue(job_store.complete(claim,output));self.assertFalse(job_store.complete(claim,output))
        fresh=student_store.inbox('max:11')[0];self.assertEqual(fresh['status'],'needs_review')
        self.assertTrue(all(x['checked'] is False for x in fresh['answers']))
        self.confirm(fresh)
        with self.assertRaises(AIServiceError):student_store.update('max:11',fresh['id'],{'action':'return','revision':1,'feedback':'Again'})

    def test_backup_restores_files_but_revokes_invites(self):
        _,a,_=self.joined();attempt=self.uploaded(a)
        student_store.invite('max:11',a['students'][1]['id'])
        archive=Path(self.temp.name)/'backup.zip';backup.create_backup(archive);restored=Path(self.temp.name)/'restored';backup.restore_backup(archive,restored)
        self.assertTrue((restored/'student_uploads'/attempt['id']/'0.jpg').is_file())
        import sqlite3
        with closing(sqlite3.connect(restored/'worksheets.db')) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM student_invites').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM student_links').fetchone()[0],1)

    def test_changed_official_grade_blocks_stale_confirmation(self):
        _,a,_=self.joined();first=self.confirm(self.uploaded(a))
        student_store.update('max:11',first['id'],{'action':'return','revision':first['revision'],'feedback':'Исправьте.'})
        second=self.uploaded(a)
        with workspace_store.connection() as conn:conn.execute('UPDATE reviews SET revision=revision+1 WHERE assignment_id=?',(a['id'],))
        with self.assertRaises(AIServiceError) as error:self.confirm(second)
        self.assertEqual(error.exception.code,'review_base_conflict')
        fresh=next(x for x in student_store.inbox('max:11') if x['id']==second['id'])
        self.assertTrue(fresh['base_conflict'])
        updated=student_store.update('max:11',fresh['id'],{'action':'confirm','revision':fresh['revision'],
            'reviewed':True,'replace_review':fresh['current_review'],'answers':[
                {'task_id':t['id'],'text':'checked','score':1,'comment':''} for t in fresh['tasks']]})
        self.assertEqual(updated['status'],'confirmed')

    def test_closed_class_and_invalid_files_cannot_submit(self):
        c,a,_=self.joined()
        invalid=self.call(self.other,'post',f"/api/v2/student/assignments/{a['id']}/attempts",data={'files':(io.BytesIO(b'<html>bad</html>'),'scan.jpg')},headers={'Idempotency-Key':uuid.uuid4().hex})
        self.assertEqual(invalid.status_code,415)
        with workspace_store.connection() as conn:conn.execute('UPDATE classrooms SET archived=1 WHERE id=?',(c['id'],))
        with self.assertRaises(AIServiceError):student_store.upload('max:22',a['id'],uuid.uuid4().hex,[self.photo()])

if __name__=='__main__':unittest.main()

import json
import os
import time
import unittest
import uuid
from unittest.mock import patch
import test_students as students
from test_bot_quick import Fake
from utils import student_store, student_drafts, student_notifications, workspace_store, review_store, backup
from utils.max_bot import APIError


class DraftNotificationTests(unittest.TestCase):
    setUp=students.StudentTests.setUp
    call=students.StudentTests.call
    signed=students.StudentTests.signed
    login=students.StudentTests.login
    create=students.StudentTests.create
    compiled=students.StudentTests.compiled
    classroom=students.StudentTests.classroom
    assignment=students.StudentTests.assignment
    photo=students.StudentTests.photo
    joined=students.StudentTests.joined
    uploaded=students.StudentTests.uploaded
    confirm=students.StudentTests.confirm

    def prepare(self):
        _,a,_=self.joined();attempt=self.uploaded(a)
        v={'revision':attempt['revision'],'draft_revision':None,'request_id':uuid.uuid4().hex,'comment':'Добавьте ОДЗ.',
           'answers':[{'task_id':t['id'],'text':'ответ','score':.75,'comment':'Нужно обоснование.','checked':True} for t in a['worksheet']['tasks']]}
        return a,attempt,v

    def test_draft_reopens_without_publishing_and_enforces_ownership(self):
        a,x,v=self.prepare();url='/api/v2/student-attempts/'+x['id']+'/draft'
        response=self.call(self.client,'put',url,json=v);self.assertEqual(response.status_code,200,response.json)
        saved=response.json['draft'];self.assertEqual(saved['answers'][0]['score'],.75)
        teacher=self.call(self.client,'get',url[:-6]).json['attempt']
        self.assertEqual(teacher['draft'],saved);self.assertIsNone(teacher['answers'][0]['score'])
        pupil=self.call(self.other,'get',url[:-6]).json['attempt'];self.assertNotIn('draft',pupil);self.assertEqual(pupil['feedback'],'')
        self.assertEqual(self.call(self.other,'put',url,json=v).status_code,404)
        self.assertEqual(self.call(self.anon,'put',url,json=v).status_code,401)
        self.assertIsNone(self.call(self.other,'get','/api/v2/student/assignments/'+a['id']).json['assignment']['result'])
        # Lost response retry is idempotent, but another tab cannot replace it.
        self.assertEqual(self.call(self.client,'put',url,json=v).json['draft']['revision'],saved['revision'])
        self.assertEqual(self.call(self.client,'put',url,json=dict(v,request_id=uuid.uuid4().hex)).status_code,409)
        self.assertEqual(self.call(self.client,'put',url,json=dict(v,comment='different')).status_code,409)
        confirmed=self.call(self.client,'put',url[:-6],json=dict(v,action='confirm',reviewed=True,draft_revision=saved['revision']))
        self.assertEqual(confirmed.status_code,200,confirmed.json);self.assertIsNone(confirmed.json['attempt']['draft'])
        self.assertEqual(self.call(self.client,'put',url,json=v).status_code,409)
        with workspace_store.connection() as conn:self.assertEqual(conn.execute('SELECT count(*) FROM review_history').fetchone()[0],1)

    def test_draft_blocks_recognition_and_stale_return_and_rejects_bad_scores(self):
        _,x,v=self.prepare();saved=student_drafts.save('max:11',x['id'],v)
        from utils.gigachat_client import AIServiceError
        with workspace_store.connection() as conn, self.assertRaises(AIServiceError):student_store.enqueue(conn,'max:11',x['id'],'job',1)
        with self.assertRaises(AIServiceError):student_store.update('max:11',x['id'],{'revision':1,'action':'return','feedback':'Исправьте'})
        for score in (True,-1,.3,2,'1'):
            invalid=json.loads(json.dumps(v));invalid['answers'][0]['score']=score;invalid['request_id']=uuid.uuid4().hex;invalid['draft_revision']=saved['revision']
            with self.assertRaises(AIServiceError):student_drafts.save('max:11',x['id'],invalid)
        returned=student_store.update('max:11',x['id'],{'revision':1,'action':'return','feedback':'Исправьте','draft_revision':saved['revision']})
        self.assertIsNone(returned['draft']);self.assertEqual(returned['notification'],'queued')
        self.assertEqual(returned['answers'][0]['score'],.75)
        self.assertEqual(returned['task_feedback'][0]['comment'],'Нужно обоснование.')
        with workspace_store.connection() as conn:self.assertEqual(conn.execute('SELECT count(*) FROM reviews').fetchone()[0],0)

    def returned(self):
        _,x,_=self.prepare()
        return student_store.update('max:11',x['id'],{'revision':1,'action':'return','feedback':'Личный комментарий'})

    def notification(self):
        with workspace_store.connection() as conn:return dict(conn.execute('SELECT * FROM student_notifications').fetchone())

    @patch.dict(os.environ,{'MAX_APP_URL':'https://listok.test'})
    def test_notification_once_private_link_and_no_feedback_or_login_token(self):
        x=self.returned();fake=Fake()
        self.assertTrue(student_notifications.poll(fake));self.assertFalse(student_notifications.poll(fake))
        self.assertEqual(len(fake.messages),1);user,text,buttons=fake.messages[0];self.assertEqual(user,22)
        self.assertNotIn('Личный комментарий',text);self.assertNotIn('token=',json.dumps(buttons))
        self.assertIn('student:'+x['assignment_id'],json.dumps(buttons));self.assertEqual(self.notification()['status'],'sent')
        pupil=self.call(self.other,'get','/api/v2/student-attempts/'+x['id']).json['attempt'];self.assertNotIn('notification',pupil)

    @patch.dict(os.environ,{'MAX_APP_URL':'https://listok.test'})
    def test_rate_limit_retries_but_ambiguous_delivery_does_not(self):
        self.returned();fake=Fake()
        with patch.object(fake,'send',side_effect=APIError(429)):student_notifications.poll(fake)
        self.assertEqual(self.notification()['status'],'queued');self.assertFalse(student_notifications.poll(fake))
        with workspace_store.connection() as conn:conn.execute('UPDATE student_notifications SET due_at=0')
        with patch.object(fake,'send',side_effect=TimeoutError()):student_notifications.poll(fake)
        self.assertEqual(self.notification()['status'],'unknown');self.assertFalse(student_notifications.poll(fake))
        self.assertEqual(student_store.inbox('max:11')[0]['status'],'returned')

    def test_revocation_and_restore_cancel_delivery_keep_draft(self):
        x=self.returned();student_store.revoke('max:11',x['student_id']);fake=Fake()
        self.assertTrue(student_notifications.poll(fake));self.assertEqual(fake.messages,[]);self.assertEqual(self.notification()['status'],'cancelled')
        with workspace_store.connection() as conn:
            backup.revoke_bot_state(conn)
            self.assertEqual(conn.execute('SELECT count(*) FROM student_notifications').fetchone()[0],0)

    def test_demo_never_queues_real_delivery(self):
        x=self.returned()
        with workspace_store.connection() as conn:
            row=dict(conn.execute('SELECT * FROM student_attempts WHERE id=?',(x['id'],)).fetchone());row['revision']+=1;row['owner_id']='demo:teacher'
            student_notifications.enqueue(conn,row)
            self.assertEqual(conn.execute('SELECT status FROM student_notifications WHERE attempt_revision=?',(row['revision'],)).fetchone()[0],'demo')

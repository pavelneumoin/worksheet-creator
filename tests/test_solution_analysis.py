"""Evidence-bound solution advice and immutable grades; no keys sent to vision."""
import json
from types import SimpleNamespace
from unittest.mock import Mock,patch
import unittest
import test_students as students
from utils import solution_ai,student_store,job_store,review_store,workspace_store
from utils.gigachat_client import AIServiceError

def response(data):return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(data,ensure_ascii=False)),finish_reason='stop')])

class AnalysisTests(unittest.TestCase):
    def fake(self,unclear=False,evidence='x=2'):
        client=Mock();client.__enter__=Mock(return_value=client);client.__exit__=Mock(return_value=False)
        client.upload_file.return_value=SimpleNamespace(id_='inline:test')
        client.chat.side_effect=[response({'steps':[{'number':1,'text':'x=2','unclear':unclear}]}),response({'tasks':[{'task_id':'t1','evidence':evidence,'reason':'Проверка подстановкой.','next_step':'Укажите промежуточное преобразование.','suggested_score':.5,'uncertain':False}]})]
        return client

    def test_vision_sees_no_key_and_only_grounded_text_can_support_advice(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'scan.jpg';p.write_bytes(b'test');client=self.fake()
            with patch.object(solution_ai,'_create_client',return_value=client):data=solution_ai.analyze([{'id':'t1','question':'2x=4','answer':'KEY SECRET'}],[p])
            self.assertEqual(data['tasks'][0]['suggested_score'],.5)
            first=client.chat.call_args_list[0].args[0]
            self.assertNotIn('KEY SECRET',' '.join(m.content for m in first.messages))
            second=client.chat.call_args_list[1].args[0]
            self.assertIn('KEY SECRET',' '.join(m.content for m in second.messages))
            self.assertTrue(all(not m.attachments for m in second.messages))
            for unclear,evidence in [(True,'x=2'),(False,'invented')]:
                with patch.object(solution_ai,'_create_client',return_value=self.fake(unclear,evidence)):
                    data=solution_ai.analyze([{'id':'t1','question':'2x=4','answer':'2'}],[p])
                self.assertIsNone(data['tasks'][0]['suggested_score']);self.assertTrue(data['tasks'][0]['uncertain'])

class ReturnTests(unittest.TestCase):
    setUp=students.StudentTests.setUp
    call=students.StudentTests.call
    signed=students.StudentTests.signed
    login=students.StudentTests.login
    create=students.StudentTests.create
    compiled=students.StudentTests.compiled
    classroom=students.StudentTests.classroom
    assignment=students.StudentTests.assignment
    joined=students.StudentTests.joined
    uploaded=students.StudentTests.uploaded
    confirm=students.StudentTests.confirm
    def test_paper_review_can_be_returned_without_losing_grade(self):
        _,a,_=self.joined()
        # Seed a confirmed paper review through the normal owner transaction.
        attempt=self.confirm(self.uploaded(a))
        with workspace_store.connection() as conn:
            row=conn.execute('SELECT * FROM reviews WHERE assignment_id=?',(a['id'],)).fetchone()
            rid=row['id'];revision=row['revision']
            conn.execute('DELETE FROM student_attempts WHERE assignment_id=?',(a['id'],))
        returned=student_store.return_review('max:11',rid,{'revision':revision,'feedback':'Уточните решение.'})
        self.assertEqual(returned['status'],'returned')
        detail=self.call(self.other,'get',f"/api/v2/student/assignments/{a['id']}").json['assignment']
        self.assertTrue(detail['can_submit']);self.assertIsNotNone(detail['result'])
        second=self.uploaded(a);self.assertEqual(second['number'],2)
        self.confirm(second,1)

if __name__=='__main__':unittest.main()

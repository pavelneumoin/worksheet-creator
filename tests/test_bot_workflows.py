import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch, Mock
import uuid
from PIL import Image
from pypdf import PdfWriter
import test_reviews as reviews
from test_bot_quick import Fake
from utils import bot_login, bot_quick, bot_workflows as flow, job_store, review_store, workspace_store, backup, db, latex, max_bot
from utils.gigachat_client import AIServiceError


class Chat(Fake):
    def __init__(self): super().__init__(); self.images=[]; self.calls=[]
    def call(self,*args,**kwargs): self.calls.append((args,kwargs)); return {'success':True}
    def send_image(self,user,path,text,**kwargs):
        self.images.append((user,path.read_bytes())); self.send(user,text,**kwargs)


class BotWorkflowTests(unittest.TestCase):
    setUp=reviews.ReviewTests.setUp
    call=reviews.ReviewTests.call
    signed=reviews.ReviewTests.signed
    login=reviews.ReviewTests.login
    create=reviews.ReviewTests.create
    compiled=reviews.ReviewTests.compiled
    classroom=reviews.ReviewTests.classroom
    assignment=reviews.ReviewTests.assignment
    queued=reviews.ReviewTests.queued
    recognized=reviews.ReviewTests.recognized
    photo=reviews.ReviewTests.photo
    body=reviews.ReviewTests.body

    def item(self,action,payload=None,user=11):
        return {'id':uuid.uuid4().hex,'user_id':user,'first_name':'Учитель','action':action,'payload':payload or {}}

    def tap(self,chat,button,user=11):
        return flow.handle(chat,self.item('callback',{'callback_id':uuid.uuid4().hex,'token':button['payload'][3:]},user))

    def find_button(self,chat,text):
        return next(b for _,_,meta in reversed(chat.messages) for row in meta.get('buttons',[]) for b in row if b.get('text')==text)

    def test_private_callback_identity_and_distinct_fast_taps_are_not_dropped(self):
        update={'update_type':'message_callback','timestamp':int(time.time()*1000),
                'callback':{'callback_id':'one','payload':'lk:'+'a'*32,'user':{'user_id':11,'first_name':'Учитель','is_bot':False}},
                'message':{'recipient':{'chat_type':'dialog'}}}
        item=bot_login.event_request(update);self.assertEqual(item['user_id'],11)
        bot_login.enqueue(update);update['callback']['callback_id']='two';bot_login.enqueue(update)
        with workspace_store.connection() as conn:self.assertEqual(conn.execute("SELECT count(*) FROM bot_inbox WHERE action='callback'").fetchone()[0],2)
        update['message']['recipient']['chat_type']='chat';self.assertIsNone(bot_login.event_request(update))
        update['message']['recipient']['chat_type']='dialog';update['callback']['user']['is_bot']=True
        self.assertIsNone(bot_login.event_request(update))

    def test_actions_are_one_use_bound_to_owner_and_expire(self):
        b=flow.button(11,'Действие','next',{'assignment_id':'only-mine'})
        raw=b['payload'][3:]
        with self.assertRaises(AIServiceError):flow.take_action(22,raw)
        self.assertEqual(flow.take_action(11,raw),('next',{'assignment_id':'only-mine'}))
        with self.assertRaises(AIServiceError):flow.take_action(11,raw)
        b=flow.button(11,'Действие','next')
        with workspace_store.connection() as conn:conn.execute('UPDATE bot_actions SET expires_at=0')
        with self.assertRaises(AIServiceError):flow.take_action(11,b['payload'][3:])

    def test_chat_partial_is_only_a_draft_old_buttons_conflict_and_confirmation_is_separate(self):
        a,r=self.recognized(states=['unclear','readable','readable']);chat=Chat()
        flow.next_answer(chat,11,'Учитель',a['id'])
        half=self.find_button(chat,'½');old_one=self.find_button(chat,'1')
        self.assertEqual(len(chat.images),1)
        self.tap(chat,half)
        saved=review_store.get_review('max:11',r['id'])
        self.assertEqual(saved['draft']['answers'][0]['score'],.5)
        self.assertTrue(saved['draft']['answers'][0]['checked'])
        self.assertEqual(review_store.report('max:11',a['id'])['summary']['confirmed'],0)
        with self.assertRaises(AIServiceError):self.tap(chat,old_one)
        self.tap(chat,self.find_button(chat,'Сверил работу, подтвердить'))
        report=review_store.report('max:11',a['id'])
        self.assertEqual(report['summary']['average'],2.5)
        self.assertEqual(report['summary']['percent'],83.3)

    def test_web_draft_wins_over_stale_chat_card(self):
        a,r=self.recognized(states=['unclear','readable','readable']);chat=Chat()
        flow.next_answer(chat,11,'Учитель',a['id']);button=self.find_button(chat,'0')
        review_store.save_draft('max:11',r['id'],self.body(r,score=.75))
        with self.assertRaises(AIServiceError):self.tap(chat,button)
        self.assertEqual(review_store.get_review('max:11',r['id'])['draft']['answers'][0]['score'],.75)

    def test_pdf_selection_uses_frozen_assignment_not_generation_and_notifies_then_maps_qr(self):
        _,_,a,_=self.assignment();chat=Chat();job_store.heartbeat('qa-ai','ai')
        file=Path(self.temp.name)/'scan.pdf';writer=PdfWriter();writer.add_blank_page(width=595,height=842);writer.write(file)
        action=flow.button(11,'Выбрать','selected',{'assignment_id':a['id'],'mode':'check'})
        self.tap(chat,action);self.assertEqual(flow.current_context(11),a['id'])
        with patch('utils.bot_quick.download',return_value=[file]):
            flow.handle(chat,self.item('chat_media',{'media':[{'type':'file','url':'https://fu.oneme.ru/fixture'}]}))
        self.assertIsNone(flow.current_context(11))
        claim=job_store.claim_next('ai');self.assertEqual(claim['kind'],'batch_grade')
        directory=job_store.job_directory(claim['id'])/'pages';directory.mkdir()
        Image.new('RGB',(160,160),'white').save(directory/'page_1.jpg')
        output={'photo_count':1,'batch_pages':[{'assignment_code':a['id'],'edition_code':a['code'],'student_code':a['students'][0]['code'],
                'answers':[{'task_id':t['id'],'text':t['answer'],'state':'readable','box':[10,20,300,70]} for t in a['worksheet']['tasks']]}]}
        self.assertTrue(job_store.complete(claim,output));self.assertTrue(bot_quick.poll(chat))
        self.tap(chat,self.find_button(chat,'Прикрепить страницы по QR'))
        report=review_store.report('max:11',a['id']);self.assertEqual(report['summary']['submitted'],1);self.assertEqual(report['summary']['confirmed'],0)
        review=review_store.get_review('max:11',next(s['review_id'] for s in report['students'] if s['review_id']))
        self.assertEqual(review['answers'][0]['sources'],[{'photo_index':0,'box':[10,20,300,70]}])

    def test_repeat_uses_only_confirmed_weak_tasks_and_no_pupil_answers(self):
        a,r=self.recognized();body=self.body(r);body['answers'][1].update(score=.5,text='PRIVATE_PUPIL_ANSWER')
        review_store.update('max:11',r['id'],body);chat=Chat();job_store.heartbeat('qa-ai','ai')
        flow.repeat_preview(chat,11,a['id']);self.tap(chat,self.find_button(chat,'Создать черновик повторения'))
        with workspace_store.connection() as conn:
            row=conn.execute("SELECT payload FROM jobs WHERE kind='variant'").fetchone();payload=json.loads(row[0])
        self.assertEqual(len(payload['worksheet']['tasks']),1)
        self.assertEqual(payload['worksheet']['tasks'][0]['id'],a['worksheet']['tasks'][1]['id'])
        self.assertNotIn('PRIVATE_PUPIL_ANSWER',row[0]);self.assertNotIn(r['student_code'],row[0])
        job_store.complete(job_store.claim_next('ai'),{'worksheets':[payload['worksheet']]})
        self.assertTrue(bot_quick.poll(chat));material,revision=bot_quick.draft('max:11')
        self.assertEqual(len(material['worksheet']['tasks']),1);self.assertEqual(material['revision'],revision)

    def test_today_reuses_print_files_and_queues_missing_forms_once(self):
        _,_,a,_=self.assignment();chat=Chat()
        day=flow.datetime.now(flow.timezone(flow.timedelta(hours=3))).date().isoformat()
        with workspace_store.connection() as conn:conn.execute('UPDATE assignments SET scheduled_date=?',(day,))
        flow.today(chat,11);flow.today(chat,11)
        self.assertEqual(len(chat.files),4) # two explicit requests: worksheet + keys each
        with workspace_store.connection() as conn:self.assertEqual(conn.execute('SELECT count(*) FROM bot_print_queue').fetchone()[0],1)
        job_store.heartbeat('qa-compile','compile');self.assertTrue(flow.poll_print_queue(chat))
        flow.today(chat,11)
        with workspace_store.connection() as conn:self.assertEqual(conn.execute('SELECT count(*) FROM bot_print_queue').fetchone()[0],1)

    def test_restore_revokes_chat_buttons_context_and_pending_prints(self):
        flow.button(11,'Test','next')
        with workspace_store.connection() as conn:
            conn.execute('INSERT INTO bot_context VALUES(?,?,?)',(11,'a',time.time()+500))
            conn.execute('INSERT INTO bot_print_queue(id,user_id,assignment_id,created_at) VALUES(?,?,?,?)',('x',11,'a',time.time()))
            backup.revoke_bot_state(conn)
            for table in ('bot_actions','bot_context','bot_print_queue'):
                self.assertEqual(conn.execute('SELECT count(*) FROM '+table).fetchone()[0],0)

    def test_expired_scan_has_no_score_buttons_and_another_teacher_cannot_open_it(self):
        a,r=self.recognized(states=['unclear','readable','readable']);chat=Chat()
        with workspace_store.connection() as conn:conn.execute('UPDATE reviews SET photo_expires=0 WHERE id=?',(r['id'],))
        flow.next_answer(chat,11,'Учитель',a['id'])
        self.assertEqual(chat.images,[])
        with self.assertRaises(StopIteration):self.find_button(chat,'½')
        with self.assertRaises(AIServiceError):flow.next_answer(chat,22,'Другой',a['id'])

    def test_report_and_forms_send_owned_pdf_once_and_reject_another_owner(self):
        _,_,a,_=self.assignment();chat=Chat();job_store.heartbeat('qa-compile','compile')
        for kind in ('report_pdf','answer_forms'):
            payload={'assignment_id':a['id'],'_bot_user':11}
            if kind=='answer_forms':payload['mode']='class'
            job,_=job_store.submit('max:11',kind,uuid.uuid4().hex,payload)
            claim=job_store.claim_next('compile')
            base=Path(latex.OUTPUT_DIR)/('job_'+job['id'])
            base.with_suffix('.pdf').write_bytes(b'%PDF-test')
            base.with_suffix('.tex').write_text('test')
            self.assertTrue(job_store.complete(claim,{}))
            self.assertTrue(bot_quick.poll(chat));self.assertFalse(bot_quick.poll(chat))
            result=job_store.get_job('max:11',job['id'])['result']
            with self.assertRaises(AIServiceError):flow.deliver_result_file(chat,22,result,'private')
        self.assertEqual(len(chat.files),2)
        self.assertTrue(all(file.is_file() for _,file,_ in chat.files))
        self.assertEqual(len([m for m in chat.messages if 'PDF сохранён' in m[1]]),2)

    def test_image_upload_uses_official_token_shape_without_sending_authorization_to_cdn(self):
        path=Path(self.temp.name)/'image.png';Image.new('RGB',(30,30),'white').save(path)
        response=Mock(status_code=200);response.json.return_value={'photos':{'123':{'token':'uploaded-image'}}}
        with patch.dict('os.environ',{'MAX_BOT_TOKEN':'test-only'}):client=max_bot.Client()
        try:
            with patch.object(client,'call',return_value={'url':'https://photo.oneme.ru/upload'}), patch.object(client,'send') as send, patch('utils.bot_quick.media_url',side_effect=lambda value:value), patch('utils.max_bot.requests.post',return_value=response) as upload:
                client.send_image(11,path,'Сверьте ответ',buttons=[[{'type':'callback','text':'½','payload':'lk:test'}]])
                self.assertNotIn('headers',upload.call_args.kwargs)
                self.assertFalse(upload.call_args.kwargs['allow_redirects'])
                self.assertEqual(send.call_args.kwargs['attachments'],[{'type':'image','payload':{'token':'uploaded-image'}}])
        finally:client.close()

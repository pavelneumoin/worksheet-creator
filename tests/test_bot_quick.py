import json
from pathlib import Path
import socket
import uuid
from unittest.mock import patch
import unittest
import test_bot_login as login
from utils import bot_login,bot_quick,job_store,workspace_store,max_bot,backup
from utils.gigachat_client import AIServiceError
from utils.worksheet import demo_worksheet

class Fake:
    def __init__(self):self.messages=[];self.files=[]
    def send(self,user,text,**kwargs):self.messages.append((user,text,kwargs))
    def send_file(self,user,path,title):self.files.append((user,path,title))

class QuickTests(unittest.TestCase):
    setUp=login.BotLoginTests.setUp
    message=login.BotLoginTests.message

    def item(self,action,payload=None):
        return {'id':uuid.uuid4().hex,'user_id':11,'first_name':'Учитель','action':action,'payload':json.dumps(payload or {})}

    def test_private_photo_and_explicit_text_command_have_sender_identity(self):
        update=self.message('');update['message']['body']['attachments']=[{'type':'image','payload':{'url':'https://photo.oneme.ru/a'}}]
        result=bot_login.event_request(update)
        self.assertEqual((result['action'],result['user_id']),('recognize',11))
        update['message']['recipient']['chat_type']='chat';self.assertIsNone(bot_login.event_request(update))
        self.assertEqual(bot_login.event_request(self.message('/лист 2 + 2'))['payload']['text'],'2 + 2')
        self.assertIsNone(bot_login.event_request(self.message('произвольное сообщение')))

    def test_cdn_rejects_private_addresses_wrong_ports_and_deceptive_hosts(self):
        for url in ('http://fu.oneme.ru/a','https://oneme.ru.evil.test/a','https://127.0.0.1/a','https://x@fu.oneme.ru/a','https://fu.oneme.ru:444/a'):
            with self.assertRaises(AIServiceError):bot_quick.media_url(url)
        with patch('utils.bot_quick.socket.getaddrinfo',return_value=[(socket.AF_INET,1,6,'',('10.0.0.1',443))]):
            with self.assertRaises(AIServiceError):bot_quick.media_url('https://fu.oneme.ru/a')

    def test_text_to_private_draft_then_confirmation_and_stale_revision(self):
        fake=Fake();job_store.heartbeat('test','ai');job_store.heartbeat('compiler','compile')
        bot_quick.handle(fake,self.item('recognize',{'text':'2 + 2','media':[]}))
        queued=job_store.list_jobs('max:11')[0]
        self.assertEqual(queued['kind'],'recognize')
        with workspace_store.connection() as conn:self.assertEqual(conn.execute('SELECT COUNT(*) FROM bot_runs').fetchone()[0],1)
        claim=job_store.claim_next('ai');job_store.complete(claim,{'worksheets':[demo_worksheet('math')]})
        self.assertEqual(len(workspace_store.list_materials('max:11')),1)
        self.assertEqual(workspace_store.list_materials('max:22'),[])
        self.assertTrue(bot_quick.poll(fake));self.assertFalse(bot_quick.poll(fake))
        self.assertTrue(any('Ответ:' in m[1] for m in fake.messages))
        self.assertEqual(len(job_store.list_jobs('max:11')),1) # No auto compile before review.
        material,_=bot_quick.draft('max:11')
        workspace_store.put_material('max:11',material['worksheet'],'ai_draft',material['id'],material['revision'])
        with self.assertRaises(AIServiceError):bot_quick.handle(fake,self.item('compile'))
        bot_quick.handle(fake,self.item('draft'));bot_quick.handle(fake,self.item('compile'))
        self.assertEqual(job_store.list_jobs('max:11')[0]['kind'],'compile')
        with workspace_store.connection() as conn:self.assertEqual(conn.execute('SELECT COUNT(*) FROM library_publications').fetchone()[0],0)

    def test_outbound_timeout_is_not_retried_as_if_send_failed(self):
        fake=Fake();job_store.heartbeat('test','ai')
        bot_quick.handle(fake,self.item('recognize',{'text':'2+2'}))
        job_store.complete(job_store.claim_next('ai'),{'worksheets':[demo_worksheet('math')]})
        with patch.object(fake,'send',side_effect=TimeoutError()):
            with self.assertRaises(TimeoutError):bot_quick.poll(fake)
        self.assertFalse(bot_quick.poll(fake))
        bot_quick.handle(fake,self.item('draft')) # User can explicitly recover the saved result.
        self.assertTrue(any('Ответ:' in m[1] for m in fake.messages))

    def test_restore_clears_pending_bot_deliveries(self):
        fake=Fake();job_store.heartbeat('test','ai');bot_quick.handle(fake,self.item('recognize',{'text':'2+2'}))
        with workspace_store.connection() as conn:
            backup.revoke_bot_state(conn)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM bot_runs').fetchone()[0],0)

    def test_crash_before_first_preview_can_be_recovered_but_not_silently_confirmed(self):
        fake=Fake();job_store.heartbeat('test','ai');job_store.heartbeat('compiler','compile')
        bot_quick.handle(fake,self.item('recognize',{'text':'2+2'}))
        job_store.complete(job_store.claim_next('ai'),{'worksheets':[demo_worksheet('math')]})
        with workspace_store.connection() as conn:conn.execute("UPDATE bot_runs SET status='sending'")
        with self.assertRaises(AIServiceError):bot_quick.handle(fake,self.item('compile'))
        bot_quick.handle(fake,self.item('draft'))
        self.assertTrue(any('Ответ:' in m[1] for m in fake.messages))
        self.assertEqual(bot_quick.draft('max:11')[1],1)

if __name__=='__main__':unittest.main()

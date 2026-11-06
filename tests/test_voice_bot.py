import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid
import test_bot_quick as quick
from utils import bot_login, bot_quick, bot_workflows, job_store, job_runner, voice_sheet, workspace_store
from utils.gigachat_client import AIServiceError
from utils.worksheet import demo_worksheet


class VoiceTests(unittest.TestCase):
    setUp=quick.QuickTests.setUp
    message=quick.QuickTests.message
    item=quick.QuickTests.item

    def audio(self,transcription=None):
        update=self.message('');update['message']['body']['attachments']=[{'type':'audio','payload':{'url':'https://audio.oneme.ru/voice'},'transcription':transcription}]
        return update

    def test_audio_private_owner_and_confirm_before_generating(self):
        event=bot_login.event_request(self.audio('Математика восьмой класс шесть уравнений'))
        self.assertEqual(event['action'],'voice');fake=quick.Fake();bot_quick.handle(fake,event)
        self.assertEqual(job_store.list_jobs('max:11'),[])
        button=fake.messages[0][2]['buttons'][0][0]
        with self.assertRaises(AIServiceError):bot_workflows.take_action(22,button['payload'][3:])
        job_store.heartbeat('ai','ai')
        bot_workflows.handle(fake,self.item('callback',{'token':button['payload'][3:],'callback_id':'x'}))
        self.assertEqual(job_store.list_jobs('max:11')[0]['kind'],'voice_generate')
        with self.assertRaises(AIServiceError):bot_workflows.take_action(11,button['payload'][3:])
        group=self.audio();group['message']['recipient']['chat_type']='chat';self.assertIsNone(bot_login.event_request(group))

    def test_audio_is_queued_cleaned_and_does_not_create_sheet_before_consent(self):
        fake=quick.Fake();job_store.heartbeat('ai','ai');source=Path(self.temp.name)/'voice.audio';source.write_bytes(b'OggSfixture')
        with patch('utils.voice_sheet.download',return_value=source):bot_quick.handle(fake,bot_login.event_request(self.audio()))
        claim=job_store.claim_next('ai');self.assertEqual(claim['kind'],'voice_transcribe')
        with patch('utils.voice_sheet.transcribe',return_value='Математика восьмой класс шесть уравнений'):
            self.assertEqual(job_runner.execute(claim['id']),0)
        output=json.loads((job_store.job_directory(claim['id'])/'result.json').read_text(encoding='utf-8'))
        job_store.complete(claim,output);job_store.maintain();self.assertFalse(job_store.job_directory(claim['id']).exists())
        self.assertEqual(workspace_store.list_materials('max:11'),[])
        self.assertTrue(bot_quick.poll(fake));self.assertIn('Проверьте тему',fake.messages[-1][1])

    def test_generation_keeps_settings_latex_and_private_material(self):
        sheet=demo_worksheet('math');sheet['settings'].update(columns=2,field='none');sheet['grade']='8'
        model=Mock();model.chat.return_value=SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content=json.dumps(sheet,ensure_ascii=False)))])
        context=Mock();context.__enter__=Mock(return_value=model);context.__exit__=Mock(return_value=False)
        with patch('utils.voice_sheet._create_client',return_value=context):result=voice_sheet.generate('Математика восьмой класс шесть уравнений')
        self.assertEqual(result['settings']['columns'],2);self.assertEqual(result['settings']['field'],'none')
        fake=quick.Fake();bot_quick.handle(fake,self.item('voice_brief',{'text':'Математика восьмой класс шесть уравнений'}))
        token=fake.messages[-1][2]['buttons'][0][0]['payload'][3:];job_store.heartbeat('ai','ai')
        bot_workflows.handle(fake,self.item('callback',{'token':token,'callback_id':'id'}))
        job_store.complete(job_store.claim_next('ai'),{'worksheets':[result]});bot_quick.poll(fake)
        material,revision=bot_quick.draft('max:11');self.assertEqual(revision,1)
        self.assertEqual(workspace_store.list_materials('max:22'),[])
        self.assertEqual(material['worksheet']['grade'],'8')

    def test_limits_invalid_audio_and_no_remote_decoder_protocols(self):
        for value in ('','x'*2001,{},'abc\x00abcxyz'):
            with self.assertRaises(AIServiceError):voice_sheet.brief(value)
        model=Path(self.temp.name)/'model';(model/'am').mkdir(parents=True);(model/'am/final.mdl').write_bytes(b'fixture')
        with patch.dict(os.environ,{'LISTOK_VOSK_MODEL':str(model),'LISTOK_FFMPEG':'ffmpeg'}),patch('utils.voice_sheet.subprocess.run',side_effect=ValueError()) as run:
            with self.assertRaises(AIServiceError):voice_sheet.transcribe(Path(self.temp.name)/'audio',self.temp.name)
            args=run.call_args.args[0];self.assertEqual(args[args.index('-protocol_whitelist')+1],'file,pipe');self.assertEqual(run.call_args.kwargs['timeout'],30)

    def test_command_correction_and_pupil_login_command(self):
        self.assertEqual(bot_login.event_request(self.message('/тема Физика 9 класс механика'))['payload']['text'],'Физика 9 класс механика')
        self.assertEqual(bot_login.event_request(self.message('/my'))['action'],'student_home')
        self.assertEqual(bot_login.event_request(self.message('/voice'))['action'],'voice_help')

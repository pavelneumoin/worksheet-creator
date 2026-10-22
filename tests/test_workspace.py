"""Structured flow, provider contract, layout and MAX signature regression checks."""
import hashlib
import hmac
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "backend"))
from utils.worksheet import (demo_worksheet, validate_worksheet, rich_text_to_tex,
                             parse_ai_worksheet, worksheet_tex, compile_worksheet)
from utils.gigachat_client import AIServiceError
from utils.max_auth import validate_init_data
from utils import structured_ai


class WorksheetTests(unittest.TestCase):
    def test_roundtrip_preserves_questions_answers_and_order(self):
        for subject in ("math", "physics"):
            sheet = demo_worksheet(subject)
            self.assertEqual(parse_ai_worksheet(json.dumps(sheet), subject), sheet)
            self.assertEqual(len(sheet["tasks"]), 3)

    def test_plain_text_never_becomes_tex_commands(self):
        self.assertEqual(rich_text_to_tex("50% & #1"), r"50\% \& \#1")
        self.assertIn(r"\textbackslash{}input", rich_text_to_tex(r"\input{secret}"))
        self.assertEqual(rich_text_to_tex("Ответ $x=2$ см"), "Ответ $x=2$ см")

    def test_unsafe_or_malformed_math_rejected(self):
        for text in (r"$\input{secret}$", r"$\end{document}$", "$x", "$x{1$", "$x}1$", "$^^41$", "$%hello$", "$$", r"$\vspace{99cm}$"):
            with self.subTest(text=text), self.assertRaises(AIServiceError):
                rich_text_to_tex(text)

    def test_invalid_shapes_rejected(self):
        for update in ({"tasks": []}, {"tasks": None}, {"settings": []},
                       {"settings": {"columns": True}}, {"settings": {"tasks_per_page": 7}},
                       {"settings": {"field": "evil"}}, {"title": []}, {"subject": []}):
            with self.subTest(update=update), self.assertRaises(AIServiceError):
                validate_worksheet({**demo_worksheet("math"), **update})
        sheet = demo_worksheet("math");sheet["tasks"][1]["id"] = "1"
        with self.assertRaises(AIServiceError): validate_worksheet(sheet)

    def test_page_count_is_layout_not_prompt(self):
        sheet=demo_worksheet("math");sheet["settings"].update(tasks_per_page=2,columns=2)
        tex=worksheet_tex(sheet)
        self.assertEqual(tex.count(r"\newpage"),1)
        self.assertEqual(tex.count(r"\begin{minipage}"),3)
        self.assertNotIn("19",tex)  # answers never appear on student sheet
        sheet["settings"]["field"]="none"
        self.assertNotIn(r"\WriteField",worksheet_tex(sheet))

    def test_bad_ai_json_is_provider_error(self):
        for raw in ("not json", "[]", '{"tasks":[]}'):
            with self.subTest(raw=raw), self.assertRaises(AIServiceError) as err:
                parse_ai_worksheet(raw,"math")
            self.assertEqual(err.exception.status,502)

    def test_failed_answers_remove_partial_files(self):
        from utils import latex
        with patch.object(latex,"_compile_single_doc",side_effect=[("sheet.pdf",None),(None,"bad answers")]), patch.object(latex,"_remove_output") as cleanup:
            with self.assertRaises(AIServiceError):compile_worksheet(demo_worksheet("math"),"test")
            self.assertEqual(cleanup.call_count,2)

    def test_extra_page_is_rejected_and_outputs_removed(self):
        from utils import latex
        with tempfile.TemporaryDirectory() as temp:
            for name in ('test.pdf','test_keys.pdf'):
                (Path(temp)/name).write_bytes(b'fake PDF reader fixture')
            with patch.object(latex,'OUTPUT_DIR',temp), \
                 patch.object(latex,'_compile_single_doc',side_effect=[('test.pdf',None),('test_keys.pdf',None)]), \
                 patch('utils.worksheet.PdfReader',return_value=SimpleNamespace(pages=[1,2])):
                with self.assertRaises(AIServiceError) as err:
                    compile_worksheet(demo_worksheet('math'),'test')
                self.assertEqual(err.exception.code,'layout_overflow')
                self.assertFalse((Path(temp)/'test.pdf').exists())
                self.assertFalse((Path(temp)/'test_keys.pdf').exists())


class ProviderTests(unittest.TestCase):
    def fake_client(self, fail=False):
        class Client:
            def __init__(self):self.ids=[];self.deleted=[];self.messages=[]
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def upload_file(self,stream,purpose):
                assert purpose=="general";self.ids.append(str(len(self.ids)+1));return SimpleNamespace(id_=self.ids[-1])
            def delete_file(self,file_id):self.deleted.append(file_id)
            def chat(self,request):
                self.messages.extend(request.messages)
                if fail:raise TimeoutError("test provider timeout")
                return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop",message=SimpleNamespace(content=json.dumps(demo_worksheet("math"))))])
        return Client()

    def test_multiple_photos_use_separate_messages_and_cleanup(self):
        client=self.fake_client()
        with tempfile.TemporaryDirectory() as temp:
            paths=[]
            for index in range(2):
                p=Path(temp)/f"{index}.png";p.write_bytes(b"test");paths.append(str(p))
            with patch.object(structured_ai,"_create_client",return_value=client):
                result=structured_ai.generate("math",image_paths=paths)
        attachments=[m.attachments for m in client.messages if m.attachments]
        self.assertEqual(attachments,[["1"],["2"]]);self.assertEqual(client.deleted,["1","2"])
        self.assertEqual(len(result["tasks"]),6)
        self.assertEqual([t['id'] for t in result['tasks']],['1','2','3','4','5','6'])

    def test_unchanged_variant_is_never_presented_as_new(self):
        client=self.fake_client()
        with patch.object(structured_ai,'_create_client',return_value=client), self.assertRaises(AIServiceError) as error:
            structured_ai.generate('math',original=demo_worksheet('math'),difficulty='harder')
        self.assertEqual(error.exception.code,'ai_variant_unchanged')

    def test_malformed_response_has_one_bounded_repair_and_keeps_teacher_instructions(self):
        client=self.fake_client()
        def response(content):
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content=content))])
        with patch.object(client,'chat',side_effect=[response('bad JSON'),response(json.dumps(demo_worksheet('math')))]) as chat, patch.object(structured_ai,'_create_client',return_value=client):
            sheet=structured_ai.generate('math',text='Источник',instructions='Только уравнения')
        self.assertEqual(len(sheet['tasks']),3)
        self.assertEqual(chat.call_count,2)
        self.assertIn('Только уравнения',chat.call_args.args[0].messages[0].content)

    def test_instructions_apply_to_every_page_and_can_skip_an_excluded_page(self):
        client=self.fake_client()
        def response(content):
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content=content))])
        with tempfile.TemporaryDirectory() as temp:
            paths=[Path(temp)/'1.jpg',Path(temp)/'2.jpg']
            for path in paths:path.write_bytes(b'test')
            with patch.object(client,'chat',side_effect=[response('{"tasks":[]}'),response(json.dumps(demo_worksheet('math')))]) as chat,patch.object(structured_ai,'_create_client',return_value=client):
                result=structured_ai.generate('math',image_paths=paths,instructions='Только уравнения')
        self.assertEqual(len(result['tasks']),3)
        self.assertEqual(result['title'],demo_worksheet('math')['title'])
        for call in chat.call_args_list:self.assertIn('Только уравнения',call.args[0].messages[0].content)
        self.assertEqual(client.deleted,['1','2'])

    def test_provider_failure_still_deletes_uploaded_photo(self):
        client=self.fake_client(fail=True)
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/"photo.png";p.write_bytes(b"test")
            with patch.object(structured_ai,"_create_client",return_value=client), self.assertRaises(AIServiceError) as err:
                structured_ai.generate("math",image_paths=[str(p)])
        self.assertEqual(err.exception.status,504);self.assertEqual(client.deleted,["1"])


class MaxTests(unittest.TestCase):
    token="test-token-only"
    def signed(self,**updates):
        data={"auth_date":"1000","user":json.dumps({"id":42,"first_name":"Тест"},ensure_ascii=False),**updates}
        payload="\n".join(f"{key}={data[key]}" for key in sorted(data))
        key=hmac.new(b"WebAppData",self.token.encode(),hashlib.sha256).digest()
        data["hash"]=hmac.new(key,payload.encode(),hashlib.sha256).hexdigest()
        return urlencode(data)
    def test_valid_signature(self):self.assertEqual(validate_init_data(self.signed(),self.token,now=1100)["id"],42)
    def test_tampered_duplicate_expired_or_future_rejected(self):
        raw=self.signed()
        for value,now in ((raw.replace("auth_date=1000","auth_date=1001"),1100),(raw+"&auth_date=1000",1100),(raw,5000),(raw,900),("",1100)):
            with self.subTest(value=value,now=now),self.assertRaises(AIServiceError):validate_init_data(value,self.token,now=now)


class WorkspaceApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from utils import db
        cls.tmp=tempfile.TemporaryDirectory(prefix='workspace-api-')
        cls.db_patch=patch.object(db,'DB_PATH',str(Path(cls.tmp.name)/'test.db'))
        cls.db_patch.start()
        import app
        db.init_db()
        cls.sync_patch = patch.dict(app.app.config, LISTOK_ALLOW_SYNC_API=True)
        cls.sync_patch.start()
        app.app.config['LISTOK_AUTH_MODE'] = 'local'
        cls.client=app.app.test_client()
        login=cls.client.post('/api/v2/auth/local')
        assert login.status_code==200, login.json
        cls.client.environ_base['HTTP_X_CSRF_TOKEN']=login.json['csrf_token']
    @classmethod
    def tearDownClass(cls):
        cls.sync_patch.stop();cls.db_patch.stop();cls.tmp.cleanup()
    def test_requires_content_review(self):
        response=self.client.post('/api/v2/compile',json={"worksheet":demo_worksheet("math")})
        self.assertEqual(response.status_code,400);self.assertEqual(response.json["code"],"review_required")
    def test_no_fake_recognition_without_key(self):
        with patch('workspace_api.get_ai_status',return_value={"ai_ready":False,"ai_message":"no key"}):
            response=self.client.post('/api/v2/recognize',data={"text":"2+2"})
        self.assertEqual(response.status_code,503);self.assertNotIn("worksheet",response.json)
    def test_invalid_photo_is_rejected_before_provider(self):
        response=self.client.post('/api/v2/recognize',data={"files":(io.BytesIO(b"plain"),"x.png")})
        self.assertEqual(response.status_code,415)
    def test_demo_is_manual(self):
        result=self.client.get('/api/v2/demo?subject=physics')
        self.assertEqual(result.json["source"],"manual_demo")
        self.assertEqual(len(result.json["worksheet"]["tasks"]),3)
    def test_uploaded_files_removed_after_provider_error(self):
        seen=[]
        def fail(*args,**kwargs):
            seen.extend(kwargs['image_paths']);self.assertTrue(all(Path(x).exists() for x in seen))
            raise AIServiceError("upstream failed","ai_provider_error",502)
        with patch('workspace_api.get_ai_status',return_value={"ai_ready":True}),patch('workspace_api.structured_ai.generate',side_effect=fail):
            response=self.client.post('/api/v2/recognize',data={"files":(io.BytesIO(b"\x89PNG\r\n\x1a\nbytes"),"x.png")})
        self.assertEqual(response.status_code,502);self.assertTrue(seen);self.assertFalse(any(Path(x).exists() for x in seen))


if __name__=='__main__':unittest.main()

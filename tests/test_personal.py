"""Offline integration checks: genuine signed launch fixtures, isolated owners and files."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app/backend'))
from utils import db, workspace_store, latex
from utils.sessions import COOKIE, token_hash
from utils.worksheet import demo_worksheet


class PersonalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_patch = patch.object(db, 'DB_PATH', str(Path(self.temp.name) / 'private.db'))
        self.db_patch.start(); self.addCleanup(self.db_patch.stop)
        db.init_db()
        import app
        self.app = app.app
        self.mode = patch.dict(self.app.config, {'LISTOK_AUTH_MODE':'max', 'TESTING':True})
        self.mode.start(); self.addCleanup(self.mode.stop)
        self.env = patch.dict(os.environ, {'MAX_BOT_TOKEN':'test-only-token', 'MAX_APP_URL':'https://listok.test'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.output = patch.object(latex, 'OUTPUT_DIR', self.temp.name)
        self.output.start(); self.addCleanup(self.output.stop)
        self.client = self.app.test_client()
        self.other = self.app.test_client()
        self.anon = self.app.test_client()
        self.login(self.client, 11)
        self.login(self.other, 22)

    def signed(self, owner, age=0):
        data = {'auth_date':str(int(time.time())-age), 'query_id':'fixture-' + str(owner),
                'user':json.dumps({'id':owner, 'first_name':'Учитель'}, ensure_ascii=False)}
        key = hmac.new(b'WebAppData', b'test-only-token', hashlib.sha256).digest()
        data['hash'] = hmac.new(key, '\n'.join(f'{k}={data[k]}' for k in sorted(data)).encode(), hashlib.sha256).hexdigest()
        return urlencode(data)

    def call(self, client, method, path, **kwargs):
        return getattr(client, method)(path, base_url='https://listok.test', **kwargs)

    def login(self, client, owner):
        result = self.call(client, 'post', '/api/v2/auth/max', json={'init_data':self.signed(owner)})
        self.assertEqual(result.status_code, 200, result.json)
        client.environ_base['HTTP_X_CSRF_TOKEN'] = result.json['csrf_token']
        return result

    def create(self):
        result = self.call(self.client, 'post', '/api/v2/materials', json={'worksheet':demo_worksheet('math')})
        self.assertEqual(result.status_code, 201, result.json)
        return result.json['material']

    def test_cookie_is_opaque_secure_httponly_and_session_revoked(self):
        result = self.login(self.client, 11)
        cookie = result.headers['Set-Cookie']
        for flag in ('HttpOnly', 'Secure', 'SameSite=None'):
            self.assertIn(flag, cookie)
        raw = self.client.get_cookie(COOKIE, domain='listok.test').value
        self.assertNotIn('max:11', raw)
        self.assertEqual(self.call(self.client,'post','/api/v2/auth/logout').status_code,200)
        self.client.set_cookie(COOKIE, raw, domain='listok.test')
        self.assertEqual(self.call(self.client,'get','/api/v2/materials').status_code,401)

    def test_tampered_expired_and_missing_max_data_rejected(self):
        for raw in (self.signed(11).replace('fixture-11','fixture-22'), self.signed(11,4000), ''):
            self.assertEqual(self.call(self.anon,'post','/api/v2/auth/max',json={'init_data':raw}).status_code,401)

    def test_local_login_cannot_be_used_in_production_or_remotely(self):
        self.assertEqual(self.call(self.anon,'post','/api/v2/auth/local').status_code,403)
        with patch.dict(self.app.config, {'LISTOK_AUTH_MODE':'local'}):
            response=self.anon.post('/api/v2/auth/local',environ_overrides={'REMOTE_ADDR':'203.0.113.1'})
            self.assertEqual(response.status_code,403)

    def test_csrf_and_cross_origin_requests_rejected(self):
        payload={'worksheet':demo_worksheet('math')}
        for headers in ({'X-CSRF-Token':'wrong'}, {'Origin':'https://attacker.test'}, {'Sec-Fetch-Site':'cross-site'}):
            self.assertEqual(self.call(self.client,'post','/api/v2/materials',json=payload,headers=headers).status_code,403)

    def test_anonymous_cannot_use_old_or_new_api_or_direct_files(self):
        for method,path in [('get','/api/v2/materials'),('post','/api/v2/compile'),('post','/api/v2/recognize'),
                            ('post','/api/v2/variant'),('get','/api/history'),('post','/api/compile'),
                            ('post','/api/process'),('post','/api/generate_similar'),('get','/api/generated/x.pdf')]:
            with self.subTest(path=path):
                self.assertEqual(self.call(self.anon,method,path).status_code,401)

    def test_materials_isolated_on_list_read_update_delete(self):
        material=self.create(); url='/api/v2/materials/' + material['id']
        self.assertEqual(self.call(self.other,'get','/api/v2/materials').json['materials'],[])
        for method in ('get','put','delete'):
            kwargs={} if method=='get' else {'json':{'worksheet':demo_worksheet('math'),'revision':1}}
            self.assertEqual(self.call(self.other,method,url,**kwargs).status_code,404)
        self.assertEqual(self.call(self.client,'get',url).status_code,200)

    def test_same_max_user_on_second_device_sees_materials(self):
        material=self.create()
        self.login(self.other,11)
        self.assertEqual(self.call(self.other,'get','/api/v2/materials').json['materials'][0]['id'],material['id'])

    def test_stale_revision_cannot_overwrite_or_delete(self):
        material=self.create(); url='/api/v2/materials/' + material['id']
        body={'worksheet':demo_worksheet('physics'),'revision':1}
        result=self.call(self.client,'put',url,json=body)
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json['material']['revision'],2)
        self.assertEqual(self.call(self.client,'put',url,json=body).status_code,409)
        self.assertEqual(self.call(self.client,'delete',url,json={'revision':1}).status_code,409)
        self.assertEqual(self.call(self.client,'delete',url,json={'revision':2}).status_code,200)

    def test_pdf_tex_and_native_download_ticket_ownership_and_expiry(self):
        for name in ('private.pdf','answers.pdf','private.tex'):
            (Path(self.temp.name)/name).write_text('test-owned-file')
        links=workspace_store.add_artifact('max:11','private.pdf','answers.pdf','private.tex')
        for name in ('private.pdf','answers.pdf','private.tex'):
            path='/api/generated/' + name
            with self.call(self.client,'get',path) as response:
                self.assertEqual(response.status_code,200)
            self.assertEqual(self.call(self.other,'get',path).status_code,404)
        path='/api/v2/exports/' + links['artifact_id']
        self.assertEqual(self.call(self.other,'post',path).status_code,404)
        ticket=self.call(self.client,'post',path).json
        with self.call(self.anon,'get',ticket['pdf_url']) as response:
            self.assertEqual(response.status_code,200)
        self.assertEqual(self.call(self.anon,'get',ticket['pdf_url'].replace('private.pdf','else.pdf')).status_code,404)
        with workspace_store.connection() as conn:
            conn.execute('UPDATE download_tickets SET expires_at=0')
        self.assertEqual(self.call(self.anon,'get',ticket['pdf_url']).status_code,404)
        fresh=self.call(self.client,'post',path).json
        self.call(self.client,'post','/api/v2/auth/logout')
        self.assertEqual(self.call(self.anon,'get',fresh['pdf_url']).status_code,404)

    def test_foreign_artifact_cannot_attach_and_old_pdf_detaches_on_edit(self):
        links=workspace_store.add_artifact('max:11','private.pdf',None,'private.tex')
        body={'worksheet':demo_worksheet('math'),'artifact_id':links['artifact_id']}
        self.assertEqual(self.call(self.other,'post','/api/v2/materials',json=body).status_code,404)
        material=self.call(self.client,'post','/api/v2/materials',json=body).json['material']
        self.assertEqual(material['result']['artifact_id'],links['artifact_id'])
        edited=self.call(self.client,'put','/api/v2/materials/'+material['id'],json={'worksheet':demo_worksheet('physics'),'revision':1})
        self.assertIsNone(edited.json['material']['result'])

    def test_legacy_history_never_shows_unowned_or_other_users(self):
        db.save_worksheet('old','', '', '', owner_id=None)
        db.save_worksheet('other','', '', '', owner_id='max:22')
        db.save_worksheet('mine','', '', '', owner_id='max:11')
        result=self.call(self.client,'get','/api/history')
        self.assertEqual([x['topic'] for x in result.json['history']],['mine'])


if __name__=='__main__': unittest.main()

"""Private MAX commands, authenticated webhook, single-use login and owner isolation."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app/backend'))
from utils import bot_login, db, max_bot, workspace_store
from utils.gigachat_client import AIServiceError
from utils.worksheet import demo_worksheet


class BotLoginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        setting = patch.object(db, 'DB_PATH', str(Path(self.temp.name) / 'bot.db'))
        setting.start(); self.addCleanup(setting.stop)
        db.init_db()
        import app
        self.app = app.app
        mode = patch.dict(self.app.config, {'LISTOK_AUTH_MODE': 'max', 'TESTING': True})
        mode.start(); self.addCleanup(mode.stop)
        env = patch.dict(os.environ, {'LISTOK_BOT_LOGIN_ENABLED': '1', 'MAX_APP_URL': 'https://listok.test',
                                    'MAX_BOT_USERNAME': 'fixture_bot', 'MAX_WEBHOOK_SECRET': 's' * 43})
        env.start(); self.addCleanup(env.stop)
        self.client = self.app.test_client()
        self.other = self.app.test_client()

    def call(self, path, data=None, headers=None, client=None):
        return (client or self.client).post(path, base_url='https://listok.test', json=data, headers=headers or {})

    def started(self):
        return {'update_type': 'bot_started', 'timestamp': int(time.time() * 1000),
                'chat_id': 111, 'user': {'user_id': 11, 'first_name': 'Учитель', 'is_bot': False}}

    def message(self, text='/start', chat_type='dialog'):
        return {'update_type': 'message_created', 'timestamp': int(time.time() * 1000),
                'message': {'sender': {'user_id': 11, 'first_name': 'Учитель', 'is_bot': False},
                            'recipient': {'chat_type': chat_type, 'user_id': 999},
                            'body': {'mid': 'fixture-mid', 'text': text}}}

    def webhook(self, update, secret='s' * 43):
        return self.call('/api/max/webhook', update, {'X-Max-Bot-Api-Secret': secret})

    def login(self, client, owner):
        token = bot_login.issue(owner, 'Учитель')
        response = self.call('/api/v2/auth/bot', {'token': token, 'confirm': True}, client=client)
        self.assertEqual(response.status_code, 200, response.json)
        client.environ_base['HTTP_X_CSRF_TOKEN'] = response.json['csrf_token']
        return response

    def test_authenticated_webhook_is_durable_and_duplicate_safe(self):
        update = self.started()
        self.assertEqual(self.webhook(update).status_code, 200)
        self.assertEqual(self.webhook(update).status_code, 200)
        with workspace_store.connection() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM bot_inbox').fetchone()[0], 1)
        item = bot_login.claim()
        self.assertEqual(item['user_id'], 11)
        self.assertIsNone(bot_login.claim())
        bot_login.finish(item['id'], True)
        self.webhook(update)
        self.assertIsNone(bot_login.claim())

    def test_webhook_rejects_bad_missing_unicode_and_disabled_secrets(self):
        for secret in ('', 'wrong', 'я' * 43):
            self.assertEqual(self.webhook(self.started(), secret).status_code, 403)
        with patch.dict(os.environ, {'LISTOK_BOT_LOGIN_ENABLED': '0'}):
            self.assertEqual(self.webhook(self.started()).status_code, 403)
        self.assertIsNone(bot_login.claim())

    def test_webhook_body_is_bounded_and_json_required(self):
        self.assertEqual(self.webhook({'padding': 'x' * 66000}).status_code, 413)
        self.assertEqual(self.webhook([]).status_code, 400)
        self.assertIsNone(bot_login.claim())

    def test_commands_only_in_private_dialogs_and_no_forwarded_identity(self):
        for kind in ('chat', 'channel', None):
            self.assertIsNone(bot_login.event_request(self.message(chat_type=kind)))
        for text in ('hello', '/start anything', '/help more', ''):
            self.assertIsNone(bot_login.event_request(self.message(text)))
        message = self.message()
        message['message']['sender']['is_bot'] = True
        self.assertIsNone(bot_login.event_request(message))
        message = self.message()
        message['message']['link'] = {'sender': {'user_id': 22}}
        self.assertEqual(bot_login.event_request(message)['user_id'], 11)

    def test_old_future_malformed_and_bot_events_are_ignored(self):
        for bad in (None, [], {}, {'update_type': 'bot_added'}):
            self.assertIsNone(bot_login.event_request(bad))
        for offset in (-601000, 61000):
            update = self.started(); update['timestamp'] += offset
            self.assertIsNone(bot_login.event_request(update))
        for owner in (True, 0, -1, '11', None):
            update = self.started(); update['user']['user_id'] = owner
            self.assertIsNone(bot_login.event_request(update))

    def test_preview_does_not_login_or_consume_and_explicit_confirmation_required(self):
        token = bot_login.issue(11, '<script>fixture</script>')
        for _ in range(2):
            result = self.call('/api/v2/auth/bot/preview', {'token': token})
            self.assertEqual(result.json['first_name'], '<script>fixture</script>')
            self.assertNotIn('Set-Cookie', result.headers)
        result = self.call('/api/v2/auth/bot', {'token': token})
        self.assertEqual(result.status_code, 400)
        result = self.call('/api/v2/auth/bot', {'token': token, 'confirm': True})
        self.assertEqual(result.status_code, 200)
        for flag in ('Secure', 'HttpOnly', 'SameSite=None'):
            self.assertIn(flag, result.headers['Set-Cookie'])
        self.assertEqual(self.call('/api/v2/auth/bot', {'token': token, 'confirm': True}, client=self.other).status_code, 401)

    def test_expired_invalid_replaced_disabled_and_cross_origin_login_rejected(self):
        old = bot_login.issue(11, 'Учитель')
        fresh = bot_login.issue(11, 'Учитель')
        for token in (old, '', 'x' * 43, None, {'value': fresh}):
            self.assertEqual(self.call('/api/v2/auth/bot/preview', {'token': token}).status_code, 401)
        for headers in ({'Origin': 'https://other.test'}, {'Sec-Fetch-Site': 'cross-site'}):
            self.assertEqual(self.call('/api/v2/auth/bot', {'token': fresh, 'confirm': True}, headers).status_code, 403)
        with patch.dict(os.environ, {'LISTOK_BOT_LOGIN_ENABLED': '0'}):
            self.assertEqual(self.call('/api/v2/auth/bot/preview', {'token': fresh}).status_code, 401)
        with patch('utils.bot_login.time.time', return_value=time.time() + 301):
            self.assertEqual(self.call('/api/v2/auth/bot/preview', {'token': fresh}).status_code, 401)

    def test_token_storage_contains_hash_only_and_concurrent_redeem_is_atomic(self):
        raw = bot_login.issue(11, 'Учитель')
        with workspace_store.connection() as conn:
            row = dict(conn.execute('SELECT * FROM bot_login_tokens').fetchone())
        self.assertNotIn(raw, str(row))
        def redeem(_):
            try:
                return bot_login.lookup(raw, consume=True)['owner_id']
            except AIServiceError:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            result = list(pool.map(redeem, range(4)))
        self.assertEqual(result.count('max:11'), 1)

    def test_bot_login_preserves_owner_isolation_and_same_account_on_second_device(self):
        self.login(self.client, 11)
        saved = self.call('/api/v2/materials', {'worksheet': demo_worksheet('math')})
        self.assertEqual(saved.status_code, 201)
        self.login(self.other, 22)
        result = self.other.get('/api/v2/materials', base_url='https://listok.test')
        self.assertEqual(result.json['materials'], [])
        self.login(self.other, 11)
        result = self.other.get('/api/v2/materials', base_url='https://listok.test')
        self.assertEqual(result.json['materials'][0]['id'], saved.json['material']['id'])

    def test_reply_targets_sender_privately_and_token_stays_out_of_query(self):
        class FakeClient:
            calls = []
            def call(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                return {'message': {}}
        fake = FakeClient()
        max_bot.reply(fake, {'user_id': 11, 'first_name': 'Учитель', 'action': 'login'})
        args, kwargs = fake.calls[-1]
        self.assertEqual(args, ('POST', '/messages'))
        self.assertEqual(kwargs['params']['user_id'], 11)
        self.assertNotIn('chat_id', kwargs['params'])
        url = kwargs['json']['attachments'][0]['payload']['buttons'][0][0]['url']
        self.assertTrue(url.startswith('https://listok.test/bot-login.html#token='))
        self.assertNotIn('?', url)
        raw = url.split('#token=')[1]
        self.assertEqual(bot_login.lookup(raw)['owner_id'], 'max:11')

    def test_confirmation_page_cannot_be_framed_and_is_not_cached(self):
        response = self.client.get('/bot-login.html', base_url='https://listok.test')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        response.close()

    def test_inbox_does_not_replay_ambiguous_send_after_crash(self):
        bot_login.enqueue(self.started())
        item = bot_login.claim()
        with workspace_store.connection() as conn:
            conn.execute('UPDATE bot_inbox SET updated_at=?', (time.time() - 61,))
        self.assertIsNone(bot_login.claim())
        with workspace_store.connection() as conn:
            self.assertEqual(conn.execute('SELECT status FROM bot_inbox WHERE id=?', (item['id'],)).fetchone()[0], 'failed')


if __name__ == '__main__':
    unittest.main()

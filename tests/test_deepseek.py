import io
import os
import sys
from pathlib import Path
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

import httpx
from gigachat.models import Chat, Messages, MessagesRole

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app/backend'))

from utils.deepseek_client import DeepSeekClient
from utils.gigachat_client import AIServiceError


class DeepSeekTests(unittest.TestCase):
    def client(self):
        env = patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'unit-test-key',
                                     'DEEPSEEK_TEXT_MODEL': 'deepseek-v4-pro',
                                     'DEEPSEEK_VISION_MODEL': 'deepseek-flash'})
        env.start(); self.addCleanup(env.stop)
        client = DeepSeekClient(); self.addCleanup(client.http.close)
        return client

    def test_image_inline_routes_to_flash_text_to_pro_and_cleans_memory(self):
        client = self.client()
        image = client.upload_file(io.BytesIO(b'\x89PNG\r\n\x1a\nfixture'))
        reply = httpx.Response(200, json={'choices': [{'message': {'content': '123'}, 'finish_reason': 'stop'}]})
        with patch.object(client.http, 'post', return_value=reply) as post:
            result = client.chat(Chat(messages=[Messages(role=MessagesRole.USER, content='Read', attachments=[image.id_])]))
            payload = post.call_args.kwargs['json']
            self.assertEqual(payload['model'], 'deepseek-flash')
            self.assertTrue(payload['messages'][0]['content'][1]['image_url']['url'].startswith('data:image/png;base64,'))
            self.assertEqual(result.choices[0].message.content, '123')
            client.chat(Chat(messages=[Messages(role=MessagesRole.USER, content='Solve')]))
            self.assertEqual(post.call_args.kwargs['json']['model'], 'deepseek-v4-pro')
        client.delete_file(image.id_)
        self.assertFalse(client.images)
        with self.assertRaises(AIServiceError): client.delete_file('legacy-provider-file')

    def test_provider_errors_never_echo_body_or_key(self):
        for status, expected in [(401, 'ai_credentials'), (402, 'ai_balance'), (429, 'ai_rate_limit'), (500, 'ai_provider_error')]:
            client = self.client()
            with patch.object(client.http, 'post', return_value=httpx.Response(status, text='unit-test-key PRIVATE DATA')):
                with self.assertRaises(AIServiceError) as cm:
                    client.chat(Chat(messages=[Messages(role=MessagesRole.USER, content='Synthetic')]))
                self.assertEqual(cm.exception.code, expected)
                self.assertNotIn('PRIVATE', str(cm.exception))
                self.assertNotIn('unit-test', str(cm.exception))

    def test_invalid_and_truncated_responses_are_not_successful_sheets(self):
        client = self.client()
        for body in [{}, {'choices': []}, {'choices': [{'message': {'content': '  '}}]}]:
            with patch.object(client.http, 'post', return_value=httpx.Response(200, json=body)):
                with self.assertRaises(AIServiceError): client.chat(Chat(messages=[]))

    def test_sheet_images_are_transcribed_then_solved_without_images(self):
        from utils import structured_ai
        from utils.worksheet import demo_worksheet
        import json
        sheet = demo_worksheet('math')
        responses = [NS(choices=[NS(message=NS(content='Синтетические условия'), finish_reason='stop')]),
                     NS(choices=[NS(message=NS(content=json.dumps(sheet)), finish_reason='stop')])]
        client = self.client()
        with patch.dict(os.environ, {'LISTOK_AI_PROVIDER':'deepseek'}), \
             patch.object(structured_ai, '_create_client', return_value=client), \
             patch('builtins.open', return_value=io.BytesIO(b'\x89PNG\r\n\x1a\nfixture')), \
             patch.object(client, 'chat', side_effect=responses) as chat:
            structured_ai.generate('math', image_paths=['synthetic.png'])
            first, second = [c.args[0] for c in chat.call_args_list]
            self.assertTrue(any(m.attachments for m in first.messages))
            self.assertFalse(any(m.attachments for m in second.messages))
            self.assertIn('Синтетические условия', second.messages[-1].content)
        self.assertFalse(client.images)

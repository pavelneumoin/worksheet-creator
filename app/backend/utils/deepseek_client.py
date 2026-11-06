"""Official DeepSeek transport. Images stay in memory and use inline data URLs."""
import base64
import os
import secrets
from types import SimpleNamespace

import httpx

from utils.gigachat_client import AIServiceError


def configuration():
    return (os.environ.get('DEEPSEEK_API_KEY', '').strip(),
            os.environ.get('DEEPSEEK_TEXT_MODEL', 'deepseek-v4-pro').strip(),
            os.environ.get('DEEPSEEK_VISION_MODEL', 'deepseek-flash').strip())


class DeepSeekClient:
    def __init__(self, model=None):
        self.key, self.text_model, self.vision_model = configuration()
        if not self.key:
            raise AIServiceError('Сервис обработки пока не подключён.', 'ai_not_configured', 503)
        if self.text_model != 'deepseek-v4-pro' or self.vision_model != 'deepseek-flash':
            raise AIServiceError('Проверьте настройки моделей на сервере.', 'ai_configuration_error', 503)
        if model and model not in (self.text_model, self.vision_model):
            raise AIServiceError('Выбрана недоступная модель.', 'unsupported_model', 400)
        self.images = {}
        self.http = httpx.Client(base_url='https://api.deepseek.com',
                                 timeout=httpx.Timeout(180, connect=15), follow_redirects=False)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.images.clear()
        self.http.close()

    def upload_file(self, stream, purpose='general'):
        # Compatibility with the existing recognition pipeline; no provider file is created.
        raw = stream.read(20 * 1024 * 1024 + 1)
        if len(raw) > 20 * 1024 * 1024:
            raise AIServiceError('Изображение слишком большое.', 'input_limit', 400)
        if raw.startswith(b'\xff\xd8\xff'):
            mime = 'image/jpeg'
        elif raw.startswith(b'\x89PNG\r\n\x1a\n'):
            mime = 'image/png'
        elif raw.startswith((b'GIF87a', b'GIF89a')):
            mime = 'image/gif'
        elif raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
            mime = 'image/webp'
        else:
            raise AIServiceError('Используйте изображение JPEG или PNG.', 'invalid_image', 400)
        ident = 'inline:' + secrets.token_hex(16)
        self.images[ident] = 'data:' + mime + ';base64,' + base64.b64encode(raw).decode('ascii')
        return SimpleNamespace(id_=ident)

    def delete_file(self, file_id):
        if not file_id.startswith('inline:'):
            # An earlier provider's upload must never be mistaken for a local image.
            raise AIServiceError('Вложение относится к другому сервису.', 'provider_mismatch', 409)
        self.images.pop(file_id, None)

    def chat(self, chat):
        messages, vision = [], False
        for item in chat.messages:
            role = getattr(item.role, 'value', item.role)
            content = item.content
            attachments = getattr(item, 'attachments', None) or []
            if attachments:
                vision = True
                content = [{'type': 'text', 'text': content or ''}]
                for file_id in attachments:
                    if file_id not in self.images:
                        raise AIServiceError('Изображение недоступно. Загрузите его повторно.', 'invalid_image', 400)
                    content.append({'type': 'image_url', 'image_url': {
                        'url': self.images[file_id], 'detail': 'original'}})
            messages.append({'role': role, 'content': content})
        payload = {'model': self.vision_model if vision else self.text_model,
                   'messages': messages, 'stream': False,
                   'reasoning_effort': 'low' if vision else 'high',
                   'max_tokens': min(24000, max(8192, (getattr(chat, 'max_tokens', None) or 8000) * 2))}
        try:
            response = self.http.post('/chat/completions', json=payload,
                                      headers={'Authorization': 'Bearer ' + self.key})
        except httpx.TimeoutException as exc:
            raise AIServiceError('Обработка заняла слишком много времени. Повторите позже.', 'ai_timeout', 504) from exc
        except httpx.HTTPError as exc:
            raise AIServiceError('Сервис обработки временно недоступен.', 'ai_provider_error', 502) from exc
        if response.status_code != 200:
            messages_by_status = {
                401: ('Проверьте ключ сервиса на сервере.', 'ai_credentials', 503),
                402: ('Недостаточно средств на счёте сервиса обработки.', 'ai_balance', 503),
                429: ('Сервис перегружен. Повторите через минуту.', 'ai_rate_limit', 429),
            }
            raise AIServiceError(*messages_by_status.get(response.status_code,
                                  ('Сервис обработки временно недоступен.', 'ai_provider_error', 502)))
        try:
            data = response.json()
            choice = data['choices'][0]
            content = choice['message']['content']
            if not isinstance(content, str) or not content.strip():
                raise ValueError('empty content')
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=content), finish_reason=choice.get('finish_reason'))])
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AIServiceError('Не удалось получить полный ответ. Повторите запрос.', 'ai_invalid_response', 502) from exc

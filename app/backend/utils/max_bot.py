"""MAX API client. Tokens, outbound bodies and login links are never logged."""
import os
from urllib.parse import urlsplit

import requests
from utils import bot_login


def app_origin():
    value = os.environ.get('MAX_APP_URL', '').rstrip('/')
    parts = urlsplit(value)
    if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password
            or parts.path or parts.query or parts.fragment or parts.port not in (None, 443)):
        raise ValueError('MAX_APP_URL must be an HTTPS origin')
    return value


class Client:
    def __init__(self):
        token = os.environ.get('MAX_BOT_TOKEN', '').strip()
        if not token:
            raise ValueError('MAX_BOT_TOKEN is required')
        self.session = requests.Session()
        self.session.headers['Authorization'] = token
        self.verify = os.environ.get('MAX_CA_BUNDLE_FILE', '').strip() or True

    def call(self, method, path, **kwargs):
        response = self.session.request(method, 'https://platform-api2.max.ru' + path,
                                        verify=self.verify, timeout=(5, 10), allow_redirects=False, **kwargs)
        if response.status_code != 200:
            raise RuntimeError('MAX API HTTP ' + str(response.status_code))
        result = response.json()
        if not isinstance(result, dict) or result.get('success') is False:
            raise RuntimeError('MAX API rejected request')
        return result

    def close(self):
        self.session.close()


def reply(client, item):
    if item['action'] == 'help':
        body = {'text': 'ЛистОК помогает подготовить задания, варианты и PDF, назначить работу классу и собрать отчёт.\n\n'
                        'Отправьте /start — получите личную ссылку для входа на 5 минут. '
                        'Откройте её и подтвердите свой профиль. В кабинете можно начать с готового примера.\n\n'
                        'Условия и ответы ИИ проверяет учитель. Оценки попадают в отчёт после вашего подтверждения.'}
    else:
        origin = app_origin()
        token = bot_login.issue(item['user_id'], item['first_name'])
        url = origin + '/bot-login.html#token=' + token
        body = {'text': 'ЛистОК — от задания до рабочего листа и отчёта.\n\n'
                        'Откройте свой кабинет по кнопке. Ссылка действует 5 минут и только один раз; '
                        'не пересылайте её. Для нового входа отправьте /start.',
                'attachments': [{'type': 'inline_keyboard', 'payload': {'buttons': [
                    [{'type': 'link', 'text': 'Открыть ЛистОК', 'url': url}]]}}]}
    result = client.call('POST', '/messages', params={'user_id': item['user_id'], 'disable_link_preview': 'true'}, json=body)
    if not isinstance(result.get('message'), dict):
        raise RuntimeError('MAX API did not confirm message')

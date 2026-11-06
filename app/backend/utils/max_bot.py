"""MAX API client. Tokens, outbound bodies and login links are never logged."""
import os
import time
import re
from urllib.parse import urlsplit

import requests
from utils import bot_login

class AttachmentPending(RuntimeError):
    pass


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
        self._message_times = {}

    def call(self, method, path, **kwargs):
        # MAX allows two messages per second in one conversation. The single
        # delivery worker reuses this client for previews, files and login replies.
        if method == 'POST' and path == '/messages':
            params = kwargs.get('params', {})
            recipient = ('user', str(params['user_id'])) if 'user_id' in params else ('chat', str(params.get('chat_id')))
            now = time.monotonic()
            previous = self._message_times.get(recipient)
            if previous is not None and previous + .55 > now:
                time.sleep(previous + .55 - now)
                now = time.monotonic()
            # Reserve before the request: an ambiguous timeout may still be delivered.
            self._message_times[recipient] = now
            if len(self._message_times) > 1024:
                self._message_times = {key: stamp for key, stamp in self._message_times.items() if now - stamp < 1}
        response = self.session.request(method, 'https://platform-api2.max.ru' + path,
                                        verify=self.verify, timeout=(5, 10), allow_redirects=False, **kwargs)
        if response.status_code != 200:
            try:
                if response.json().get('code')=='attachment.not.ready':raise AttachmentPending()
            except ValueError:pass
            raise RuntimeError('MAX API HTTP ' + str(response.status_code))
        result = response.json()
        if not isinstance(result, dict) or result.get('success') is False:
            raise RuntimeError('MAX API rejected request')
        return result

    def send(self,user,text,attachments=None,buttons=None):
        body={'text':text}
        if attachments:body['attachments']=list(attachments)
        if buttons:body.setdefault('attachments',[]).append({'type':'inline_keyboard','payload':{'buttons':buttons}})
        for attempt in range(4):
            try:
                result=self.call('POST','/messages',params={'user_id':user,'disable_link_preview':'true'},json=body)
                if not isinstance(result.get('message'),dict):raise RuntimeError('MAX did not confirm delivery')
                return
            except AttachmentPending:
                if attempt==3:raise
                time.sleep(2**attempt)

    def send_file(self,user,path,title):
        from utils.bot_quick import media_url
        if not path.is_file() or path.stat().st_size>20*1024*1024:raise RuntimeError('PDF unavailable')
        upload=self.call('POST','/uploads',params={'type':'file'})
        filename=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',title)[:180]
        with path.open('rb') as stream:
            response=requests.post(media_url(upload.get('url')),files={'data':(filename,stream,'application/pdf')},timeout=(5,60),verify=self.verify,allow_redirects=False)
        if response.status_code!=200:raise RuntimeError('MAX upload failed')
        result=response.json();token=result.get('token')
        if not isinstance(token,str) or not token:raise RuntimeError('MAX upload token missing')
        self.send(user,title,attachments=[{'type':'file','payload':{'token':token}}])

    def close(self):
        self.session.close()

    def send_image(self, user, path, text, buttons=None):
        from utils.bot_quick import media_url
        if not path.is_file() or path.stat().st_size > 5 * 1024 * 1024: raise RuntimeError('Image unavailable')
        upload = self.call('POST', '/uploads', params={'type':'image'})
        with path.open('rb') as stream:
            response = requests.post(media_url(upload.get('url')), files={'data':('answer.png',stream,'image/png')},
                                     timeout=(5,40),verify=self.verify,allow_redirects=False)
        if response.status_code != 200: raise RuntimeError('MAX image upload failed')
        data = response.json(); photos = data.get('photos', {})
        token = data.get('token') or next((v.get('token') for v in photos.values() if isinstance(v,dict) and v.get('token')),None)
        if not isinstance(token,str) or not token: raise RuntimeError('MAX image token missing')
        self.send(user,text,attachments=[{'type':'image','payload':{'token':token}}],buttons=buttons)


def reply(client, item):
    if item['action'] not in ('help','login'):
        from utils import bot_quick
        from utils.gigachat_client import AIServiceError
        try:bot_quick.handle(client,item)
        except AIServiceError as exc:client.send(item['user_id'],str(exc))
        return
    if item['action'] == 'help':
        body = {'text': 'ЛистОК помогает подготовить задания, варианты и PDF, назначить работу классу и собрать отчёт.\n\n'
                        'Быстрый лист: /quick или пришлите фото. /today — комплект на сегодня. /check — проверить пачку, /next — сомнительные ответы, /summary — итог урока, /repeat — повторить ошибки. /draft — черновик, /pdf — собрать, /files — повторить PDF, /cancel — отменить ожидание сканов.\n\n'
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
                    [{'type': 'link', 'text': 'Открыть ЛистОК', 'url': url}],
                    [{'type':'message','text':'Быстрый лист'},{'type':'message','text':'На печать сегодня'}],
                    [{'type':'message','text':'Проверить пачку'},{'type':'message','text':'Итог урока'}],
                    [{'type':'message','text':'Следующий сомнительный'},{'type':'message','text':'Повторить ошибки'}]]}}]}
    result = client.call('POST', '/messages', params={'user_id': item['user_id'], 'disable_link_preview': 'true'}, json=body)
    if not isinstance(result.get('message'), dict):
        raise RuntimeError('MAX API did not confirm message')

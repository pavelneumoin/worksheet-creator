"""Register this deployment's authenticated webhook and command menu, without sending messages."""
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))
from dotenv import load_dotenv
load_dotenv(ROOT / '.env', override=False)
from utils import max_bot


def main():
    secret = os.environ.get('MAX_WEBHOOK_SECRET', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,256}', secret):
        raise SystemExit('Configure MAX_WEBHOOK_SECRET: 32–256 URL-safe characters.')
    url = max_bot.app_origin() + '/api/max/webhook'
    client = max_bot.Client()
    try:
        identity = client.call('GET', '/me')
        if not identity.get('is_bot') or identity.get('username') != os.environ.get('MAX_BOT_USERNAME'):
            raise RuntimeError('Bot identity mismatch')
        subscriptions = client.call('GET', '/subscriptions').get('subscriptions', [])
        if any(item.get('url') != url for item in subscriptions):
            raise RuntimeError('Another webhook exists; review it before changing the integration')
        client.call('POST', '/subscriptions', json={
            'url': url, 'update_types': ['bot_started', 'message_created', 'message_callback'], 'secret': secret})
        client.call('PATCH', '/me/commands', json={'commands': [
            {'name': 'start', 'description': 'Открыть личный кабинет ЛистОК'},
            {'name': 'login', 'description': 'Получить новую ссылку для входа'},
            {'name': 'quick', 'description': 'Создать лист прямо в чате'},
            {'name': 'today', 'description': 'PDF для сегодняшних уроков'},
            {'name': 'check', 'description': 'Проверить PDF с работами класса'},
            {'name': 'next', 'description': 'Следующий сомнительный ответ'},
            {'name': 'summary', 'description': 'Итог урока и отчёт класса'},
            {'name': 'repeat', 'description': 'Лист по ошибкам класса'},
            {'name': 'cancel', 'description': 'Отменить ожидание сканов'},
            {'name': 'draft', 'description': 'Посмотреть последний черновик'},
            {'name': 'pdf', 'description': 'Подтвердить задания и собрать PDF'},
            {'name': 'files', 'description': 'Повторить готовые PDF'},
            {'name': 'help', 'description': 'Как подготовить лист и отчёт'}]})
        check = client.call('GET', '/subscriptions').get('subscriptions', [])
        if not any(item.get('url') == url for item in check):
            raise RuntimeError('Webhook registration was not confirmed')
        print('MAX: bot identity, HTTPS webhook and command menu configured. No messages sent.')
    finally:
        client.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('MAX configuration failed (' + type(exc).__name__ + '). Check identity and existing subscriptions.', file=sys.stderr)
        raise SystemExit(1)

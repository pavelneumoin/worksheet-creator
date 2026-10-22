"""Read-only checks of configured provider accounts; never prints credentials."""
import argparse
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env', override=False)
sys.path.insert(0, str(ROOT / 'app' / 'backend'))


def main():
    parser = argparse.ArgumentParser(description='Check ListOK provider access without sending messages or worksheets.')
    parser.add_argument('--gigachat', action='store_true')
    parser.add_argument('--max', action='store_true')
    args = parser.parse_args()
    failed = False
    if args.gigachat:
        from utils.gigachat_client import _create_client, get_ai_status
        try:
            with _create_client() as client:
                models = client.get_models()
                names = [item.id_ for item in models.data]
                configured = get_ai_status()['ai_model']
                if configured not in names:
                    raise ValueError('Configured model unavailable')
                print('GigaChat: API доступен; настроенная модель есть в списке. Распознавание фото ещё не проверено.')
        except Exception as exc:
            print('GigaChat: проверка не пройдена (' + type(exc).__name__ + '). Проверьте .env, scope и сертификаты.')
            failed = True
    if args.max:
        import requests
        token = os.environ.get('MAX_BOT_TOKEN', '').strip()
        if not token:
            print('MAX: заполните MAX_BOT_TOKEN в .env.'); failed = True
        else:
            try:
                ca = os.environ.get('MAX_CA_BUNDLE_FILE', '').strip()
                response = requests.get('https://platform-api2.max.ru/me', headers={'Authorization': token}, timeout=20, verify=ca or True)
                response.raise_for_status()
                data = response.json()
                expected = os.environ.get('MAX_BOT_USERNAME', '').strip()
                if not data.get('is_bot') or (expected and data.get('username') != expected):
                    raise ValueError('Bot identity mismatch')
                print('MAX: токен и имя бота подтверждены API. Открытие мини-приложения ещё нужно проверить в MAX.')
            except Exception as exc:
                print('MAX: проверка не пройдена (' + type(exc).__name__ + ').'); failed = True
    if not (args.max or args.gigachat):
        parser.print_help()
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())

"""Read-only deployment checks. Never prints configuration values or secrets."""
import argparse
import ipaddress
import json
from pathlib import Path
import re
import ssl
from urllib.parse import urlsplit

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def valid_origin(value):
    if not isinstance(value, str) or re.search(r'\s', value):
        return False
    try:
        parts = urlsplit(value)
        if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password
                or parts.path not in ('', '/') or parts.query or parts.fragment
                or parts.port not in (None, 443)):
            return False
        host = parts.hostname
        if not re.fullmatch(r'[a-zA-Z0-9.-]+', host) or '.' not in host:
            return False
        if host.endswith(('.test', '.invalid', '.localhost', '.local')):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return all(re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', p)
                       for p in host.split('.'))
    except ValueError:
        return False


def check_config(settings, root):
    errors = []
    for key in ('MAX_BOT_TOKEN', 'MAX_BOT_USERNAME', 'GIGACHAT_CREDENTIALS', 'GIGACHAT_MODEL'):
        if not str(settings.get(key) or '').strip():
            errors.append(f'Заполните {key}.')
    if not valid_origin(settings.get('MAX_APP_URL') or ''):
        errors.append('MAX_APP_URL должен содержать публичный HTTPS-адрес без пути и параметров.')
    if settings.get('LISTOK_AUTH_MODE') not in (None, '', 'max'):
        errors.append('Для публикации используйте LISTOK_AUTH_MODE=max.')
    try:
        ssl.create_default_context(cafile=str(root / '.local-certs/gigachat-ca.pem'))
    except (OSError, ssl.SSLError):
        errors.append('Нужен читаемый PEM-набор .local-certs/gigachat-ca.pem.')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--url', help='Также проверить публичный HTTPS-запуск без входа и AI-запросов.')
    args = parser.parse_args()
    errors = check_config(dotenv_values(args.env_file, interpolate=False), args.env_file.resolve().parent)
    if args.url:
        if not valid_origin(args.url):
            errors.append('Проверяемый URL должен быть публичным HTTPS-адресом.')
        else:
            import requests
            try:
                base = args.url.rstrip('/')
                for path in ('/', '/api/health/ready'):
                    response = requests.get(base + path, timeout=20, allow_redirects=False)
                    if response.status_code != 200:
                        errors.append(f'{path}: HTTP {response.status_code}.')
                    elif path.endswith('/ready') and response.json().get('ready') is not True:
                        errors.append('Обработчики очереди не готовы.')
                login = requests.get(base + '/api/v2/auth/me', timeout=20, allow_redirects=False)
                if login.status_code != 200 or login.json().get('local_available') is not False:
                    errors.append('Публичный вход MAX не готов или разрешён локальный вход.')
                private = requests.get(base + '/api/v2/materials', timeout=20, allow_redirects=False)
                if private.status_code != 401:
                    errors.append('Проверка закрытого кабинета без входа не пройдена.')
            except (requests.RequestException, ValueError):
                errors.append('HTTPS-проверка не выполнена: проверьте DNS, сертификат и доступность.')
    print(json.dumps({'ok': not errors, 'errors': errors}, ensure_ascii=False, indent=2))
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())

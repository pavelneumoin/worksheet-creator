import sys
import os
sys.path.append(r"c:\Users\NeumoinPD\YandexDisk\Latex\Проекты 10С\Проекты\Драндров\ИТ проект\app\backend")

from config import GIGACHAT_CREDENTIALS, GIGACHAT_SCOPE
from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole

print(f"Using Scope: {GIGACHAT_SCOPE}")
print(f"Credentials start with: {GIGACHAT_CREDENTIALS[:10]}...")

try:
    with GigaChat(credentials=GIGACHAT_CREDENTIALS, scope=GIGACHAT_SCOPE, verify_ssl_certs=False) as giga:
        response = giga.chat(Chat(
            messages=[Messages(role=MessagesRole.USER, content="Привет! Просто ответь 'ОК', это тест.")]
        ))
        print("SUCCESS. GigaChat replied:")
        print(response.choices[0].message.content)
except Exception as e:
    print("ERROR:")
    print(e)

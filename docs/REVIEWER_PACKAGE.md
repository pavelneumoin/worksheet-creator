# Пакет для проверяющего

В репозитории лежит исходный код, `requirements.txt`, Dockerfile и команды
запуска. Готовый проверенный образ публикуется в GitHub Release вместе с
контрольной суммой. Перед запуском проверяющему нужны три вещи:

1. архив `listok-image.tar.gz` и файл `listok-image.sha256` из одного релиза;
2. этот репозиторий или ZIP исходников;
3. отдельный защищённый файл `.env` с ключом DeepSeek и, если проверяется
   настоящий вход MAX, с токеном конкурсного бота.

Ключи не входят в репозиторий и Docker-образ. Это необходимо: образ можно
скачать, а секрет после публикации нельзя отозвать у всех копий. Передавайте
`.env` только лично капитану/проверяющему через согласованный закрытый канал.

## Запуск образа

Проверяющий выполняет команды из каталога с архивом:

```bash
sha256sum --check listok-image.sha256
gunzip -c listok-image.tar.gz | docker load
git clone https://github.com/pavelneumoin/worksheet-creator.git
cd worksheet-creator
cp /защищённый/путь/.env .env
mkdir -p .local-certs
docker compose up -d --no-build --wait
curl --fail http://127.0.0.1:3005/api/health/ready
```

Для публичного HTTPS-запуска с MAX:

```bash
docker compose -f compose.yaml -f compose.https.yaml -f compose.bot.yaml up -d --no-build --wait
```

`MAX_APP_URL` должен быть HTTPS-адресом сервиса без пути к файлу, а этот же
адрес должен быть привязан владельцем бота к мини-приложению MAX.

## Файл `.env` для закрытой передачи

В `.env` проверяющий заполняет реальные значения вместо `<...>`:

```dotenv
LISTOK_AUTH_MODE=max
LISTOK_AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=<ключ из platform.deepseek.com>
DEEPSEEK_TEXT_MODEL=deepseek-v4-pro
DEEPSEEK_VISION_MODEL=deepseek-flash

MAX_BOT_TOKEN=<токен конкурсного бота MAX>
MAX_BOT_USERNAME=ideya_fiks_126_bot
MAX_APP_URL=https://<адрес-проверки>
MAX_WEBHOOK_SECRET=<случайная строка минимум 32 символа>
```

Для запуска без MAX-бота можно оставить только DeepSeek и временно использовать
локальный режим, но конкурсный сценарий проверяется через MAX. Токен нейросети
не нужно вводить в интерфейсе: приложение читает его только из окружения
серверного контейнера и не показывает в ответах, логах или PDF.

## Если нужен Docker Hub

Docker Hub нужен только для передачи образа ссылкой. После `docker login`:

```bash
docker tag listok:night7 <логин>/listok:2026-11-07
docker push <логин>/listok:2026-11-07
```

Проверяющий загружает образ командой `docker pull <логин>/listok:2026-11-07`.
Файл `.env` всё равно передаётся отдельно; не добавляйте его в образ и не
публикуйте токен в Docker Hub.

## Что отправляет капитан

- ссылку на бота MAX: `https://max.ru/ideya_fiks_126_bot`;
- ссылку на GitHub: `https://github.com/pavelneumoin/worksheet-creator`;
- ссылку на GitHub Release с архивом образа и SHA256;
- `.env` с ключами — только проверяющему в закрытом сообщении, если это
  разрешено организаторами;
- короткое сообщение: «Образ загружается через `docker load`, затем запуск
  выполняется по `docs/REVIEWER_PACKAGE.md`».

Публикация репозитория и образа сама по себе не отправляет конкурсную заявку.
Финальную форму отправляет капитан команды.

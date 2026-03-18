<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/Flask-000000?style=for-the-badge&logo=flask&logoColor=white" alt="Flask" />
  <img src="https://img.shields.io/badge/GigaChat_AI-Sber-21A038?style=for-the-badge&logo=data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjQiIGhlaWdodD0iMjQiPjxjaXJjbGUgY3g9IjEyIiBjeT0iMTIiIHI9IjEwIiBmaWxsPSJ3aGl0ZSIvPjwvc3ZnPg==&logoColor=white" alt="GigaChat" />
  <img src="https://img.shields.io/badge/LaTeX-008080?style=for-the-badge&logo=latex&logoColor=white" alt="LaTeX" />
  <img src="https://img.shields.io/badge/Telegram_Bot-26A5E4?style=for-the-badge&logo=telegram&logoColor=white" alt="Telegram" />
</p>

<h1 align="center">📝 Worksheet Creator — AI Помощник Учителя</h1>

<p align="center">
  <b>Веб-приложение + Telegram-бот для автоматической генерации рабочих листов по фотографиям задач</b><br/>
  Мультимодальный ИИ GigaChat · LaTeX-конвейер · Glassmorphism UI
</p>

<p align="center">
  <a href="#-возможности">Возможности</a> •
  <a href="#%EF%B8%8F-архитектура">Архитектура</a> •
  <a href="#-технологии">Технологии</a> •
  <a href="#-быстрый-старт">Быстрый старт</a> •
  <a href="#-деплой">Деплой</a> •
  <a href="#-авторы">Авторы</a>
</p>

---

## 🎯 Проблема

Подготовка индивидуальных рабочих листов, карточек и контрольных работ занимает **до 30% рабочего времени** учителя. Существующие решения (MathPix, ChatGPT) либо не доступны из РФ, либо не обеспечивают полного цикла **от фотографии до готового PDF**.

## ✨ Возможности

| | Функция | Описание |
|---|---------|----------|
| 📸 | **Мультимодальное распознавание** | Загрузите фото задач — GigaChat Vision извлечёт текст, формулы и структуру |
| 🤖 | **AI → LaTeX конвертация** | Автоматическое преобразование распознанного текста в профессиональный LaTeX |
| 🔄 | **Генерация Варианта 2** | Одна кнопка — и готов аналогичный вариант с изменёнными числовыми данными |
| 📄 | **PDF за секунды** | Полный конвейер компиляции: LaTeX → pdfLaTeX → готовый к печати документ |
| 🎨 | **Glassmorphism UI** | Современный интерфейс с эффектом матового стекла и анимациями |
| ⚙️ | **Выбор модели** | GigaChat **Max** (лучшее качество), **Pro** (баланс) или **Lite** (скорость) |
| 🤖 | **Telegram-бот** | Отправляйте фото задач боту и получайте PDF прямо в мессенджер |
| 📋 | **Экспорт LaTeX-кода** | Скачайте `.tex` для ручной правки в Overleaf / Papeeria |

## 🏗️ Архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│                        Пользователь                             │
│           Веб-браузер / Telegram-бот                            │
└──────────────┬────────────────────────────┬─────────────────────┘
               │  HTTP (изображение)        │  Telegram API
               ▼                            ▼
┌──────────────────────────┐  ┌──────────────────────────┐
│   Frontend (SPA)         │  │   Telegram Bot            │
│   HTML5 + CSS3 + JS      │  │   pyTelegramBotAPI        │
│   Glassmorphism UI       │  │   handlers.py             │
│   Drag-and-Drop загрузка │  └────────────┬─────────────┘
└──────────────┬───────────┘               │
               │  REST API                 │
               ▼                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Backend (Flask)                               │
│                                                                  │
│  ┌─────────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │ GigaChat Client │→ │ LaTeX Engine │→ │ PDF (pdflatex)     │  │
│  │ Vision API      │  │ Шаблонизация │  │ Готовый документ   │  │
│  └─────────────────┘  └──────────────┘  └────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## 🛠 Технологии

| Слой | Технология | Назначение |
|------|------------|------------|
| **Frontend** | HTML5, CSS3, JavaScript (ES6) | SPA с Glassmorphism-дизайном |
| **Backend** | Python 3.8+, Flask, Flask-CORS | REST API, маршрутизация |
| **AI** | Sber GigaChat (Max/Pro/Lite) | Мультимодальное распознавание и генерация |
| **Typesetting** | LaTeX (pdfLaTeX) | Профессиональная вёрстка PDF |
| **Telegram** | pyTelegramBotAPI | Бот для генерации через мессенджер |
| **Deploy** | Gunicorn, Render.com, Nginx | Облачное и серверное развёртывание |

## 🚀 Быстрый старт

### Предварительные требования

- **Python 3.8+**
- **MiKTeX** или **TeX Live** (должен быть в `PATH`)
- Аккаунт разработчика GigaChat ([developers.sber.ru](https://developers.sber.ru/))

### 1. Клонирование

```bash
git clone https://github.com/pavelneumoin/worksheet-creator.git
cd worksheet-creator
pip install -r requirements.txt
```

### 2. Настройка API

Создайте файл `app/backend/config.py` на основе примера:

```python
# app/backend/config.py
GIGACHAT_CREDENTIALS = 'ВАШ_КЛЮЧ_АВТОРИЗАЦИИ'
```

> 🔑 Получить ключ → [developers.sber.ru](https://developers.sber.ru/) → Создать проект → API-ключ GigaChat

### 3. Запуск веб-приложения

```bash
cd app
python backend/app.py
```

Откройте **http://127.0.0.1:3000** в браузере.

### 4. Запуск Telegram-бота (опционально)

```bash
cd bot
python bot.py
```

## 📖 Как пользоваться

1. **Введите тему** рабочего листа (например, "Квадратные уравнения")
2. **Укажите ФИО учителя** — отображается в шапке PDF
3. **Выберите количество задач** на странице (1–6)
4. **Выберите модель GigaChat**: Max / Pro / Lite
5. **Загрузите фото** с задачами (PNG, JPG) через Drag-and-Drop
6. **Скачайте PDF** — Вариант 1 готов к печати!
7. Нажмите **«Создать Вариант 2»** — аналогичные задачи с другими числами
8. Нажмите **«Получить LaTeX код»** для ручного редактирования

## 📁 Структура проекта

```
worksheet-creator/
├── app/                          # Веб-приложение
│   ├── backend/
│   │   ├── app.py                # Flask-сервер, REST API
│   │   ├── config.py.example     # Пример конфигурации API
│   │   ├── templates/
│   │   │   └── default_worksheet.tex  # LaTeX-шаблон рабочего листа
│   │   └── utils/
│   │       ├── gigachat_client.py     # Обёртка GigaChat API
│   │       ├── latex.py               # Компиляция LaTeX → PDF
│   │       ├── yandex.py              # Альтернативный AI-провайдер
│   │       └── db.py                  # SQLite для истории
│   ├── frontend/
│   │   ├── index.html            # Главная страница (SPA)
│   │   ├── script.js             # Клиентская логика
│   │   └── style.css             # Glassmorphism стили
│   ├── Dockerfile                # Контейнеризация
│   ├── Procfile                  # Для Render.com
│   └── requirements.txt          # Python-зависимости (app)
├── bot/                          # Telegram-бот
│   ├── bot.py                    # Точка входа бота
│   └── handlers.py               # Обработчики команд и фото
├── requirements.txt              # Python-зависимости (полный проект)
└── README.md
```

## 🌐 Деплой

### На Render.com

| Параметр | Значение |
|----------|----------|
| **Runtime** | Python 3 |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `cd app/backend && gunicorn app:app --bind 0.0.0.0:$PORT` |

**Переменные окружения:**

| Ключ | Значение |
|------|----------|
| `GIGACHAT_CREDENTIALS` | Ваш API-ключ |
| `USE_CLOUD_LATEX` | `true` |

### На собственном сервере (Nginx + PM2)

```bash
# Установка зависимостей
pip install -r requirements.txt

# Запуск через PM2
pm2 start app/backend/app.py --name worksheet-server --interpreter python3
pm2 save
```

## 📝 Настройка шаблона

Внешний вид рабочего листа настраивается в файле `app/backend/templates/default_worksheet.tex`.

Доступные LaTeX-макросы:
- `\TaskBox{№}{Текст задачи}` — рамка с номером задачи
- `\WriteField{высота}` — поле для записи решения учеником

## ⚠️ Рекомендации

- Загружайте **не более 10 задач** на одном изображении
- Используйте **чёткие фотографии** без размытия и бликов
- Для задач со сложными формулами выбирайте модель **Max**
- Модель **Lite** оптимальна для текстовых задач без формул

## 📊 Метрики

| Показатель | Значение |
|------------|----------|
| Время генерации (Lite) | 8–12 сек |
| Время генерации (Max) | 15–22 сек |
| Точность OCR формул | ~94% |
| Успешность компиляции PDF | 100% |

## 🏫 О проекте

Проект разработан в рамках конференции **«Инженеры будущего»** (направление: Веб-сайты и веб-приложения) учащимися **10 «С» класса ГБОУ «Школа 2200»**, г. Москва.

**Цель** — создать отечественный бесплатный инструмент, автоматизирующий полный цикл подготовки учебных материалов: от фотографии задачи до готового к печати PDF.

## 👥 Авторы

<table>
  <tr>
    <td align="center"><b>Драндров Максим Дмитриевич</b><br/>Учащийся 10 «С» класса</td>
    <td align="center"><b>Головков Владимир Сергеевич</b><br/>Учащийся 10 «С» класса</td>
  </tr>
</table>

**Научный руководитель:** Неумоин Павел Дмитриевич

---

<p align="center">
  <b>ГБОУ «Школа 2200» · Москва · 2026</b>
</p>

## 📄 Лицензия

MIT

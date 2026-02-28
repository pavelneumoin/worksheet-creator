import os
import base64
from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole

# Load credentials: environment variables FIRST (for Render), then config.py (for local dev)
GIGACHAT_CREDENTIALS = os.environ.get('GIGACHAT_CREDENTIALS')
GIGACHAT_SCOPE = os.environ.get('GIGACHAT_SCOPE', 'GIGACHAT_API_PERS')

# Fallback to config.py for local development
if not GIGACHAT_CREDENTIALS:
    try:
        from config import GIGACHAT_CREDENTIALS
        try:
            from config import GIGACHAT_SCOPE
        except ImportError:
            GIGACHAT_SCOPE = "GIGACHAT_API_CORP"
    except ImportError:
        GIGACHAT_CREDENTIALS = None

def clean_latex(text):
    """
    Removes markdown code blocks (```latex ... ```) if present.
    """
    text = text.strip()
    if text.startswith("```"):
        # Find first newline
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline+1:]
    if text.endswith("```"):
         text = text[:-3]
    return text.strip()

def process_image_with_gigachat(image_paths, task_count=3, model="GigaChat-Max"):
    """
    Sends images to GigaChat to extract math tasks and format them in LaTeX.
    
    Args:
        image_paths (str|list): Path or list of paths to the image files.
        task_count (int): Number of tasks to format (guides the layout).
        model (str): GigaChat model to use (only GigaChat-Max supports images).
    
    Returns:
        str: LaTeX code representing the worksheet content.
    """
    if isinstance(image_paths, str):
        image_paths = [image_paths]
    if not GIGACHAT_CREDENTIALS:
        return "Error: GIGACHAT_CREDENTIALS not found in config.py"
    
    # Only GigaChat-Max supports multimodal (image) input
    if model != "GigaChat-Max":
        return f"Error: Модель {model} не поддерживает распознавание изображений. Выберите GigaChat-Max для работы с картинками."

    # Layout calculation (reused from previous logic)
    available_height = 190 # mm
    text_buffer = 15 # mm
    try:
        count = int(task_count)
    except:
        count = 3
    if count < 1: count = 1
    if count > 6: count = 6
    raw_grid_height = (available_height / count) - text_buffer
    if raw_grid_height < 10: raw_grid_height = 10
    grid_height_mm = int(raw_grid_height)

    prompt_text = f"""Ты - профессиональный верстальщик LaTeX и математик.
Твоя задача:
1. Распознать ВСЕ математические задачи с изображения.
2. Оформить их в LaTeX строго по шаблону.
3. Разбить задачи по страницам (не более {count} задач на одной странице).
4. В конце добавить страницу с КРАТКИМИ ответами (только числа, без решений).

ПАРАМЕТРЫ ЛИСТА:
- Максимум задач на странице: {count}
- Высота поля для решения: {grid_height_mm}mm

ШАБЛОН ОФОРМЛЕНИЯ ЗАДАЧИ:
Для каждой задачи используй ОБЯЗАТЕЛЬНО такую структуру (ДВА аргумента!):
\\TaskBox{{Номер}}{{Текст задачи}}
Пример: \\TaskBox{{1}}{{Решите уравнение $x^2=4$.}}
ВАЖНО: Не забывай номер задачи в первых скобках!

\\WriteField{{{grid_height_mm}mm}}

ПРАВИЛА ВЕРСТКИ:
1.  Иди по порядку: Задача 1, Задача 2, и т.д.
2.  После каждой {count}-й задачи вставляй команду `\\newpage` (разрыв страницы).
    Пример: если задач 5, а лимит 3 -> Страница 1 (Задачи 1,2,3) -> `\\newpage` -> Страница 2 (Задачи 4,5).
3.  ОБЯЗАТЕЛЬНО вставляй `\\WriteField{{{grid_height_mm}mm}}` после КАЖДОЙ задачи. Это клетчатое поле, без него нельзя!

ИНСТРУКЦИЯ ПО ОТВЕТАМ (КРИТИЧЕСКИ ВАЖНО):
После самой последней задачи вставь `\\newpage` и напиши:
\\section*{{Ответы}}
\\begin{{tabular}}{{|c|c|}}
\\hline
№ & Ответ \\\\
\\hline
1 & $...$ \\\\
2 & $...$ \\\\
... & ... \\\\
\\hline
\\end{{tabular}}

ФОРМАТ ОТВЕТОВ:
- ТОЛЬКО числовой ответ в формате LaTeX (например: $x=2$, $15$, $\\frac{{1}}{{2}}$)
- БЕЗ пояснений, БЕЗ решений, БЕЗ комментариев
- Только итоговое значение

ИТОГОВЫЙ ВЫВОД:
Только валидный LaTeX код тела документа (Tasks + PageBreaks + Answers). Без преамбулы `\\documentclass`.
"""

    try:
        # Use selected GigaChat model
        with GigaChat(credentials=GIGACHAT_CREDENTIALS, scope=GIGACHAT_SCOPE, model=model, verify_ssl_certs=False, timeout=120) as giga:
            # 1. Upload the image files
            # Note: GigaChat needs the file uploaded to process it in chat
            attachment_ids = []
            for path in image_paths:
                with open(path, "rb") as f:
                    uploaded_file = giga.upload_file(f)
                    attachment_ids.append(uploaded_file.id_)
            
            # 2. Send the chat request with the attachment
            response = giga.chat(Chat(
                messages=[
                    Messages(
                        role=MessagesRole.USER,
                        content=prompt_text,
                        attachments=attachment_ids 
                    )
                ]
            ))
            
            raw_content = response.choices[0].message.content
            return clean_latex(raw_content)

    except Exception as e:
        return f"GigaChat Error: {str(e)}"

def generate_similar_worksheet(original_text, task_count=3, model="GigaChat-Max", difficulty="same"):
    """
    Generates a new set of similar math tasks based on the original ones.
    """
    if not GIGACHAT_CREDENTIALS:
        return "Error: GIGACHAT_CREDENTIALS not found"

    # Reuse layout calc
    available_height = 190
    text_buffer = 15
    try:
        count = int(task_count)
    except:
        count = 3
    if count < 1: count = 1
    if count > 6: count = 6
    raw_grid_height = (available_height / count) - text_buffer
    if raw_grid_height < 10: raw_grid_height = 10
    grid_height_mm = int(raw_grid_height)

    diff_prompt = ""
    if difficulty == "easier":
        diff_prompt = "\n- УРОВЕНЬ: Сделай задачи ЗАМЕТНО ПРОЩЕ (используй меньшие числа, убери сложные конструкции, сократи количество шагов)."
    elif difficulty == "harder":
        diff_prompt = "\n- УРОВЕНЬ: Сделай задачи СЛОЖНЕЕ (увеличь числа, добавь вычисления, усложни структуру уравнений/выражений)."
    else:
        diff_prompt = "\n- УРОВЕНЬ: СОХРАНИ текущую сложность."

    prompt_text = f"""Ты - профессиональный методист и верстальщик LaTeX.
Твоя задача: создать ВАРИАНТ 2 контрольной работы с ДРУГИМИ ЧИСЛАМИ.

ИСХОДНЫЙ ВАРИАНТ (Вариант 1):
\"\"\"
{original_text}
\"\"\"

КРИТИЧЕСКИ ВАЖНЫЕ ПРАВИЛА ГЕНЕРАЦИИ:{diff_prompt}
1. Для КАЖДОЙ задачи создай АНАЛОГИЧНУЮ, но с ДРУГИМИ числами
2. СОХРАНИ: тип задачи, базовую структуру
3. ИЗМЕНИ: все числовые значения (коэффициенты, константы, параметры)
4. Используй "удобные" числа для ручных вычислений (целые, простые дроби)
5. Количество задач должно ТОЧНО совпадать с исходным вариантом

ПРИМЕР ПРЕОБРАЗОВАНИЯ:
Исходная: "Решите уравнение $x^2 - 5x + 6 = 0$"
Новая:    "Решите уравнение $x^2 - 7x + 12 = 0$"

ПАРАМЕТРЫ ЛИСТА:
- Максимум задач на странице: {count}
- Высота поля для решения: {grid_height_mm}mm

ШАБЛОН ОФОРМЛЕНИЯ (СТРОГО):
\\TaskBox{{Номер}}{{Текст новой задачи}}
\\WriteField{{{grid_height_mm}mm}}

ПРАВИЛА ВЕРСТКИ:
1. После КАЖДОЙ задачи обязательно вставляй `\\WriteField{{{grid_height_mm}mm}}`
2. После каждой {count}-й задачи вставляй `\\newpage`

ОТВЕТЫ (в конце документа):
\\newpage
\\section*{{Ответы (Вариант 2)}}
\\begin{{tabular}}{{|c|c|}}
\\hline
№ & Ответ \\\\
\\hline
1 & $...$ \\\\
2 & $...$ \\\\
\\hline
\\end{{tabular}}

ФОРМАТ ОТВЕТОВ:
- ТОЛЬКО числовой ответ (например: $x=3$, $24$, $\\frac{{2}}{{3}}$)
- БЕЗ решений, БЕЗ пояснений, БЕЗ комментариев

ИТОГОВЫЙ ВЫВОД:
Только LaTeX код (Задачи + WriteField + PageBreaks + Таблица ответов).
"""

    try:
        # Use selected GigaChat model
        with GigaChat(credentials=GIGACHAT_CREDENTIALS, scope=GIGACHAT_SCOPE, model=model, verify_ssl_certs=False, timeout=120) as giga:
            response = giga.chat(prompt_text)
            raw_content = response.choices[0].message.content
            return clean_latex(raw_content)
    except Exception as e:
        return f"GigaChat Error: {str(e)}"

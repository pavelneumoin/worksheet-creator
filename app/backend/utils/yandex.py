import requests
import base64
import json
from config import FOLDER_ID, IAM_TOKEN, API_KEY

def get_auth_header():
    if IAM_TOKEN:
        return f"Bearer {IAM_TOKEN}"
    return f"Api-Key {API_KEY}"

def ocr_image(image_path):
    """
    Performs OCR using Yandex Vision API (v1).
    """
    if not API_KEY and not IAM_TOKEN:
         return "Error: No Yandex Credentials provided."

    with open(image_path, "rb") as f:
        image_content = base64.b64encode(f.read()).decode("utf-8")

    body = {
        "folderId": FOLDER_ID,
        "analyze_specs": [{
            "content": image_content,
            "features": [{
                "type": "TEXT_DETECTION",
                "text_detection_config": {
                    "language_codes": ["*"]
                }
            }]
        }]
    }

    headers = {
        "Authorization": get_auth_header()
    }

    try:
        response = requests.post(
            "https://vision.api.cloud.yandex.net/vision/v1/batchAnalyze",
            headers=headers,
            json=body
        )
        
        if response.status_code != 200:
            return f"OCR Error: {response.text}"

        response_data = response.json()
        if 'code' in response_data and response_data['code'] != 0:
             return f"OCR API Error: {response_data}"

        # Extract text from response
        full_text = ""
        results = response_data.get('results', [])
        for result in results:
             text_detection = result.get('results', [])
             for text_result in text_detection:
                  text_detection_conf = text_result.get('textDetection', {})
                  pages = text_detection_conf.get('pages', [])
                  for page in pages:
                       blocks = page.get('blocks', [])
                       for block in blocks:
                            lines = block.get('lines', [])
                            for line in lines:
                                 words = line.get('words', [])
                                 line_text = " ".join([word.get('text', '') for word in words])
                                 full_text += line_text + "\n"

        return full_text if full_text else "No text found in image."

    except Exception as e:
        return f"OCR Exception: {str(e)}"

def generate_worksheet_latex(text, topic="General", task_count=3):
    """
    Uses YandexGPT to generate LaTeX content.
    """
    if not API_KEY and not IAM_TOKEN:
        return "Error: No Yandex Credentials provided."
    
    # --- Dynamic Layout Calculation ---
    # A4 printable height approx 240mm (minus headers/margins)
    # Header: ~40mm. Title: ~15mm. 
    # Available for tasks: ~185mm.
    # We estimate task text takes ~20mm. 
    # But if there are many tasks, text must be shorter or grid smaller.
    
    available_height = 190 # mm
    
    # Calculate grid height per task
    # Formula: (Available - (TaskCount * TextBuffer)) / TaskCount
    # TextBuffer is space for the question text itself.
    text_buffer = 15 # mm
    
    try:
        count = int(task_count)
    except:
        count = 3
        
    if count < 1: count = 1
    if count > 6: count = 6

    # Calculate grid height
    raw_grid_height = (available_height / count) - text_buffer
    
    # Safety bounds
    if raw_grid_height < 10: raw_grid_height = 10
    
    grid_height_mm = int(raw_grid_height)
    
    headers = {
        "Authorization": get_auth_header(),
        "x-folder-id": FOLDER_ID
    }

    prompt = {
        "modelUri": f"gpt://{FOLDER_ID}/yandexgpt",
        "completionOptions": {
            "stream": False,
            "temperature": 0.4, # Lower temperature for more strict extraction
            "maxTokens": "8000" # Increased tokens for multi-page content
        },
        "messages": [
            {
                "role": "system",
                "text": f"""Ты - профессиональный редактор и математик. Твоя задача: восстановить математические задачи из "шумного" текста после OCR (распознавания) и оформить их в LaTeX.

КОНТЕКСТ:
Входной текст получен через Yandex Vision, который ПЛОХО распознает формулы. Он часто превращает их в кашу.
Твоя главная цель — ДОГАДАТЬСЯ, какая там была формула, и написать её правильно в LaTeX ($...$).

ТИПИЧНЫЕ ОШИБКИ OCR (исправляй их!):
- "x2" или "x 2" -> скорее всего это $x^2$
- "V a" или "\/ a" -> это корень $\\sqrt{{a}}$
- "3/4" или "3 / 4" -> это дробь $\\frac{{3}}{{4}}$
- "sin x" -> $\\sin x$
- "Log 2" -> $\\log_2$
- "a b" (слипшиеся переменные) -> $ab$
- "pi" -> $\\pi$

ПРАВИЛА ОФОРМЛЕНИЯ:
1.  Ищи ВСЕ задачи во входном тексте.
2.  Если видишь подобие формулы — оборачивай в $...$ и исправляй.
3.  Выводи результат строго в формате:
    \\TaskBox{{1}}{{Текст задачи...}}
    \\WriteField{{{grid_height_mm}mm}}
    \\TaskBox{{2}}{{...}}
    \\WriteField{{{grid_height_mm}mm}}
4.  Никаких лишних слов, преамбул и объяснений.
5.  Высота поля \\WriteField — всегда {grid_height_mm}mm.
"""
            },
            {
                "role": "user",
                "text": f"Вот грязный текст после OCR:\n\"\"\"\n{text}\n\"\"\"\n\nИзвлеки все задачи, исправь формулы и оформи в LaTeX."
            }
        ]
    }

    try:
        response = requests.post(
            "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
            headers=headers,
            json=prompt
        )
        if response.status_code == 200:
            result = response.json()
            return result['result']['alternatives'][0]['message']['text']
        else:
            return f"Error from YandexGPT: {response.text}"
    except Exception as e:
        return f"Exception: {str(e)}"

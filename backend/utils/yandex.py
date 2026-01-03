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

def generate_worksheet_latex(text, topic="General"):
    """
    Uses YandexGPT to generate LaTeX content.
    URL: https://llm.api.cloud.yandex.net/foundationModels/v1/completion
    """
    if not API_KEY and not IAM_TOKEN:
        return "Error: No Yandex Credentials provided."
    
    headers = {
        "Authorization": get_auth_header(),
        "x-folder-id": FOLDER_ID
    }

    prompt = {
        "modelUri": f"gpt://{FOLDER_ID}/yandexgpt",
        "completionOptions": {
            "stream": False,
            "temperature": 0.5,
            "maxTokens": "4000"
        },
        "messages": [
            {
                "role": "system",
                "text": "Ты - генератор рабочих листов для учителей. Твоя задача: взять входной текст (задачи или теорию) и оформить его в специальный формат LaTeX.\n\nУ тебя есть две команды:\n1. \\TaskBox{НОМЕР_ЗАДАЧИ}{ТЕКСТ_ЗАДАЧИ} - используй это для оформления каждого задания. Внутри текста задачи используй стандартный LaTeX ($...$) для формул. Переводи обычный текст в красивые формулы (например `sin^2 x`).\n2. \\WriteField{ВЫСОТА} - используй это после каждой задачи, чтобы оставить место для решения. Высоту указывай в мм (например, `40mm` для коротких, `80mm` для длинных).\n\nПравила:\n- НЕ пиши преамбулу (documentclass, usepackage).\n- НЕ пиши \\begin{document}.\n- Просто выводи список задач одну за другой.\n- Нумеруй задачи по порядку (1, 2, 3...)."
            },
            {
                "role": "user",
                "text": f"Вот материал из файла:\n{text}\n\nСформируй содержимое рабочего листа, используя \\TaskBox и \\WriteField."
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

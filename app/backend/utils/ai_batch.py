"""Small sequential batches. Checkpoint each usable draft before the next AI call."""
import json
import re

from utils import structured_ai
from utils.gigachat_client import AIServiceError
from utils.worksheet import validate_worksheet


def write_result(directory, output):
    temporary = directory / 'result.tmp'
    temporary.write_text(json.dumps(output, ensure_ascii=False), encoding='utf-8')
    temporary.replace(directory / 'result.json')


def questions(sheet):
    return {re.sub(r'\s+|\$', '', task['question']).casefold() for task in sheet['tasks']}


def generate(kind, payload, paths, directory):
    count = payload.get('variant_count', 1)
    completed, seen = [], set()
    original = payload.get('worksheet')
    if original:
        seen.update(questions(original))
    for index in range(count):
        try:
            if kind == 'recognize' and index == 0:
                sheet = structured_ai.generate(payload['subject'], image_paths=paths, text=payload['text'],
                                                instructions=payload.get('instructions', ''))
                sheet['settings'] = payload.get('settings', sheet['settings'])
            else:
                # Always use the same base for difficulty: four harder variants must not
                # become four successive increases in difficulty.
                sheet = structured_ai.generate(original['subject'], original=original,
                                                difficulty=payload.get('difficulty', 'same'))
                if questions(sheet) & seen:
                    raise AIServiceError('ИИ повторил задание из другого варианта. Готовые варианты сохранены; оставшиеся можно заказать отдельно.', 'duplicate_variant', 502)
            if count > 1:
                sheet['settings'] = dict(sheet['settings'], variant=str(index + 1))
                sheet['title'] = re.sub(r' · Вариант \d+$', '', sheet['title'])[:145] + f' · Вариант {index + 1}'
            sheet = validate_worksheet(sheet)
            if kind == 'recognize' and index == 0:
                original = sheet
            completed.append(sheet)
            seen.update(questions(sheet))
            output = {'worksheets': completed, 'requested_count': count}
            if len(completed) < count:
                output['warning'] = f'Сохранено {len(completed)} из {count} вариантов. Обработка прервалась; оставшиеся не созданы.'
            write_result(directory, output)
        except AIServiceError as exc:
            if not completed:
                raise
            output = {'worksheets': completed, 'requested_count': count,
                      'warning': f'Сохранено {len(completed)} из {count} вариантов. {exc}'}
            write_result(directory, output)
            return output
    return output

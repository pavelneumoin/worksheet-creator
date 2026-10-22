"""Opt-in comparison of final-answer OCR using synthetic, anonymous pages.

Without --run only creates local fixtures; --run uses the configured provider quota.
No real pupil photos, answer keys or problem statements are sent to GigaChat.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))

CASES = [
    {'task_id': 'fraction', 'number': 1, 'state': 'readable', 'text': '1/2', 'kind': 'fraction'},
    {'task_id': 'decimal', 'number': 2, 'state': 'readable', 'text': '-2,75', 'kind': 'negative decimal'},
    {'task_id': 'unit', 'number': 3, 'state': 'readable', 'text': '12 см', 'kind': 'Cyrillic unit'},
    {'task_id': 'blank', 'number': 4, 'state': 'blank', 'text': '', 'kind': 'explicit empty field'},
    {'task_id': 'correction', 'number': 5, 'state': 'readable', 'text': '6', 'kind': 'crossed-out 4, final 6'},
    {'task_id': 'unclear', 'number': 6, 'state': 'unclear', 'text': '', 'kind': 'occluded illegible field'},
    {'task_id': 'missing', 'number': 7, 'state': 'unclear', 'text': '', 'kind': 'number on an absent page'},
]


def make_fixtures(directory):
    from PIL import Image, ImageDraw, ImageFont
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    regular = ROOT / 'app/backend/assets/fonts/cmu/cmunrm.otf'
    handwriting = Path('C:/Windows/Fonts/segoepr.ttf')
    if not handwriting.is_file():
        handwriting = ROOT / 'app/backend/assets/fonts/cmu/cmunbi.otf'
    label = ImageFont.truetype(str(regular), 38)
    pen = ImageFont.truetype(str(handwriting), 78)
    pages = []
    for page_index, entries in enumerate((CASES[:3], CASES[3:6]), 1):
        image = Image.new('RGB', (1300, 1800), '#f3f3f1')
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((55, 45, 1245, 1755), radius=14, fill='white', outline='#bfbfbf', width=2)
        for y, text in [(95, 'Синтетический образец: конечные ответы'), (160, 'Версия: ABC123DEF456'), (220, 'Код ученика: У-ABCDE12345')]:
            draw.text((100, y), text, font=label, fill='#222222')
        for index, case in enumerate(entries):
            y = 350 + index * 440
            draw.text((100, y), f"Задание {case['number']}. Ответ:", font=label, fill='#222222')
            draw.rectangle((100, y + 75, 1195, y + 330), outline='#cfcfcf', width=2)
            if case['task_id'] == 'correction':
                draw.text((150, y + 130), '4', font=pen, fill='#234b87')
                draw.line((140, y + 145, 225, y + 235), fill='#234b87', width=7)
                draw.line((140, y + 230, 225, y + 150), fill='#234b87', width=7)
                draw.text((380, y + 130), '6', font=pen, fill='#234b87')
            elif case['task_id'] == 'unclear':
                rng = random.Random(1729)
                for _ in range(34):
                    draw.line((rng.randint(150, 335), rng.randint(y + 130, y + 250),
                               rng.randint(150, 335), rng.randint(y + 130, y + 250)), fill='#234b87', width=5)
            elif case['state'] == 'readable':
                draw.text((150, y + 130), case['text'], font=pen, fill='#234b87')
        path = directory / f'answer-control-{page_index}.jpg'
        image.save(path, quality=94)
        pages.append(path)
    manifest = {'fixture_kind': 'synthetic typography, not real pupil handwriting',
                'answer_font': handwriting.name, 'pages': [p.name for p in pages], 'cases': CASES}
    (directory / 'expected.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return pages, manifest


def measure(result, expected=CASES):
    from utils.answer_check import normalized, number
    observed = {a['task_id']: a for a in result['answers']}
    rows = []
    for case in expected:
        answer = observed[case['task_id']]
        state_ok = answer['state'] == case['state']
        text_ok = normalized(answer['text']) == normalized(case['text']) if case['state'] == 'readable' else True
        a, b = number(answer['text']), number(case['text'])
        rows.append({'task_id': case['task_id'], 'kind': case['kind'], 'expected_state': case['state'],
                     'observed_state': answer['state'], 'expected_text': case['text'], 'observed_text': answer['text'],
                     'state_correct': state_ok, 'literal_text_correct': text_ok,
                     'numeric_equivalent': a is not None and b is not None and a == b,
                     'unsafe_readable_guess': case['state'] != 'readable' and answer['state'] == 'readable'})
    return {'cases': rows, 'states_correct': sum(r['state_correct'] for r in rows),
            'readable_texts_correct': sum(r['literal_text_correct'] and r['state_correct'] for r in rows if r['expected_state'] == 'readable'),
            'unsafe_readable_guesses': sum(r['unsafe_readable_guess'] for r in rows)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='Use provider quota for at most three model batches')
    parser.add_argument('--models', nargs='+', default=['GigaChat-3-Ultra'])
    parser.add_argument('--directory', default='output/qa/answer-recognition-control')
    args = parser.parse_args()
    if not 1 <= len(args.models) <= 3 or len(set(args.models)) != len(args.models):
        parser.error('Choose one to three distinct models')
    directory = ROOT / args.directory
    pages, manifest = make_fixtures(directory)
    if not args.run:
        print('Created two synthetic pages and expected.json; no API request made.')
        return 0
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env', override=False)
    from utils.grading_ai import recognize
    from utils.gigachat_client import _create_client, AIServiceError
    with _create_client() as client:
        available = {m.id_ for m in client.get_models().data}
    tasks = [{'id': c['task_id']} for c in CASES]
    report = {'created_at': datetime.now(timezone.utc).isoformat(), 'fixture': manifest, 'models': []}
    previous_model = os.environ.get('GIGACHAT_MODEL')
    try:
        for model in args.models:
            entry = {'model': model}
            started = time.monotonic()
            if model not in available:
                entry.update(status='unavailable')
            else:
                os.environ['GIGACHAT_MODEL'] = model
                try:
                    entry.update(status='ok', result=recognize(tasks, [str(p) for p in pages]))
                    entry['metrics'] = measure(entry['result'])
                except AIServiceError as exc:
                    entry.update(status='error', code=exc.code, message=str(exc))
            entry['seconds'] = round(time.monotonic() - started, 2)
            report['models'].append(entry)
            (directory / 'comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({k: entry[k] for k in ('model', 'status', 'seconds')}, ensure_ascii=False), flush=True)
    finally:
        if previous_model is None:
            os.environ.pop('GIGACHAT_MODEL', None)
        else:
            os.environ['GIGACHAT_MODEL'] = previous_model
    print('Local diagnostic saved; application model/configuration unchanged.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

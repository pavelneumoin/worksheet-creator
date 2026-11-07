"""Build a silent, captioned MP4 from verified demo screenshots; voice-over is separate."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/video'
SCENES = [
    ('ЛистОК', 'От задания до результатов класса', 10, None, 'cover',
     ['Рабочий лист', 'Проверка', 'Результаты'],
     'ЛистОК — сервис команды «ЛатехТим» для учителей. Здесь можно подготовить рабочий лист, выдать его классу, проверить ответы и увидеть результаты. Покажем весь путь на учебных данных.'),
    ('Вход', 'Начните в MAX', 18, '21-max-menu.png', 'chat',
     ['/start', 'Открыть ЛистОК', 'Личная ссылка для входа'],
     'Откройте бота ideya_fiks_126_bot в MAX. Отправьте команду «старт» и нажмите «Открыть ЛистОК». Ссылка личная и действует пять минут. Если она устарела, запросите новую. Для входа используется ваш аккаунт MAX.'),
    ('Знакомство', 'Попробуйте демо', 14, '02-demo.png', 'screen',
     ['Готовые листы и классы', 'Учебные проверки', 'Кнопка «В мой кабинет»'],
     'Чтобы познакомиться с сервисом, откройте демо. Здесь уже подготовлены листы, классы, сканы и статистика. Сценарий проверки ведёт по основным разделам. Учебные данные отделены от вашего кабинета.'),
    ('Подготовка', 'Добавьте материал', 20, '01-create.png', 'screen',
     ['Фото, PDF или текст', 'Математика или физика', 'Оформление и варианты'],
     'В разделе «Создать лист» выберите предмет и загрузите фото учебника, PDF или текст заданий. Укажите пожелания, число вариантов и оформление: столбцы, клетчатое поле или только задачи. Нажмите «Подготовить задания», затем проверьте распознанные условия и ответы.'),
    ('Печать', 'Комплект уже рядом', 18, '03-result.png', 'screen',
     ['Лист и ответы', 'Комплект учителя', 'Другой вариант, проще, сложнее'],
     'После сборки файлы появляются на экране результата. Можно посмотреть лист, скачать ответы или полный комплект учителя. Материал сохраняется в личной библиотеке. Рядом доступны назначение классу и новые варианты: аналогичный, проще или сложнее.'),
    ('Класс', 'Ученики под кодами', 18, '19-roster.png', 'screen',
     ['Фото списка или текст', 'Проверка имён и порядка', 'Таблица «имя → код»'],
     'Создайте класс. Список учеников можно вставить текстом или распознать по фото. Проверьте имена и порядок, затем создайте коды и скачайте таблицу соответствия. Сохраните её у себя: в списке класса используются коды.'),
    ('Назначение', 'Выберите класс и дату', 16, '04-assign.png', 'screen',
     ['Готовая версия листа', 'Дата урока и срок сдачи', 'Текущий состав класса'],
     'Нажмите «Назначить классу». Выберите класс, готовую версию листа, дату проведения и срок сдачи. Назначение сохраняет именно эту версию и текущий список учеников. Работа появится в кабинете и расписании.'),
    ('Короткие ответы', 'Одна страница на ученика', 18, 'personal-answer-form.png', 'paper',
     ['Код ученика и QR', 'Номера заданий и клетки', 'Кнопка «Бланки класса»'],
     'Для быстрой проверки распечатайте бланки класса. На каждой странице есть код ученика, версия работы, QR и поля ответов. После урока достаточно сканировать эти бланки. Если нужно проверить развёрнутое решение, загрузите полную работу.'),
    ('После урока', 'Загрузите пачку PDF', 16, '06-upload-ready.png', 'screen',
     ['Проверка работ', 'Класс и назначенная работа', 'Распознать пачку'],
     'Откройте «Проверка работ», выберите класс и назначенную работу. Загрузите PDF из сканера: до сорока страниц. Имя и размер файла видны до отправки. Нажмите «Распознать пачку». Обработка идёт в фоне.'),
    ('Сопоставление', 'Проверьте коды страниц', 14, '07-batch.png', 'screen',
     ['QR помогает найти ученика', 'Проверьте сопоставление', 'Откройте очередь сомнений'],
     'Сервис сопоставляет страницы по кодам и QR. Проверьте результат. Если код не прочитан, ученика можно выбрать вручную. Затем откройте общую очередь сомнительных ответов, чтобы проходить пачку последовательно.'),
    ('Проверка', 'Сверьте ответ и балл', 18, '11-student-review.png', 'screen',
     ['Оригинал работы рядом', 'Прочитанный ответ', 'Полный или частичный балл'],
     'При проверке рядом доступны скан, прочитанный ответ и балл. Сравните их с условием и ключом. При необходимости исправьте распознанный текст, выставьте частичный балл и добавьте комментарий. Рекомендация системы помогает, а решение принимает учитель.'),
    ('Скан', 'Увеличьте нужный фрагмент', 14, '10-scan.png', 'scan',
     ['Увеличить скан', 'Масштаб и перемещение', 'Весь лист'],
     'В проверке бумажной работы нажмите «Увеличить скан». Можно приблизить фрагмент, переместить изображение или вернуться ко всему листу. Это удобно для дробей, знаков и исправлений. На телефоне поддерживается увеличение двумя пальцами.'),
    ('Автосохранение', 'Правки можно продолжить позже', 18, '../autosave.png', 'phone',
     ['Баллы и комментарии', 'Статус сохранения', 'Подтверждение отдельно'],
     'Правки проверки сохраняются автоматически. Дождитесь статуса сохранения: после повторного открытия черновик восстановится. При сбое связи можно повторить сохранение или скачать правки. Итоговая оценка и статистика меняются только после вашего подтверждения.'),
    ('Исправление', 'Верните работу с замечанием', 16, '13-pupil-feedback.png', 'phone',
     ['Что именно исправить', 'Вернуть на исправление', 'Уведомление в MAX'],
     'Чтобы вернуть работу, напишите, что нужно исправить, и нажмите соответствующую кнопку. Замечания сохранятся в кабинете ученика. Бот уведомит его в MAX, если ученик уже начал общение с ботом. В демо сообщения не отправляются.'),
    ('Ученик', 'Свои задания и результаты', 18, '12-pupil-mobile.png', 'phone',
     ['Приглашение от учителя', 'Вход через MAX', 'Только свои работы'],
     'Учитель выдаёт персональное приглашение кнопкой «Пригласить» у нужного кода. Ученик входит через MAX и вводит приглашение в своём кабинете. Здесь видны назначенные работы, подтверждённые баллы и задания, которые нужно исправить.'),
    ('Повторная сдача', 'Отправьте исправление', 16, '15-pupil-sent.png', 'phone',
     ['Фото страниц или PDF', 'Отправить исправление', 'История попыток сохраняется'],
     'Открыв работу, ученик читает замечания, прикрепляет фото или PDF и отправляет исправление. Новая попытка появляется у учителя. Прежний подтверждённый результат остаётся видимым до повторной проверки. История попыток сохраняется.'),
    ('Завуч', 'Результаты школы', 20, '16-school.png', 'screen',
     ['Классы, темы и разделы', 'Только подтверждённые баллы', 'Фильтры по учителю и датам'],
     'В разделе школы завуч видит результаты подключённых учителей. Можно выбрать класс, предметный раздел, период и тему. Сводка показывает выполнение заданий и сколько работ проверено. Несданные и неподтверждённые работы не считаются нулями.'),
    ('Отчёт', 'Подробности — в PDF и CSV', 14, 'school-report-1.png', 'paper',
     ['Сводка и диаграммы', 'Темы для внимания', 'Результаты по кодам'],
     'Кнопка «Подробный отчёт PDF» готовит документ для печати. В нём есть сводка, диаграммы, темы и таблицы по кодам. Для дальнейшей работы с данными доступна выгрузка CSV.'),
    ('Бот', 'Быстрый лист прямо в чате', 18, '20-max-files.png', 'chat',
     ['/лист — готовые задания', '/тема — описание нового листа', '/today — печать на сегодня'],
     'Рабочий лист можно подготовить прямо в чате. Пришлите фото, PDF или команду «лист» с заданиями. Для нового набора отправьте «тема» и описание. Бот покажет черновик, а после проверки соберёт PDF и сохранит материал в библиотеке.'),
    ('Голос', 'Надиктуйте тему и параметры', 20, '22-max-voice.png', 'chat',
     ['До двух минут', 'Тема, класс и число заданий', 'Проверьте расшифровку'],
     'Для голосового запроса назовите тему, класс, число заданий, сложность и оформление. Сначала проверьте расшифровку. Ошибки можно исправить командой «тема» с полным новым описанием. После подтверждения создаётся лист. Перед печатью проверьте задания и ответы.'),
    ('Начать работу', 'Ваш следующий урок — в ЛистОК', 14, None, 'end',
     ['MAX: ideya_fiks_126_bot', 'Попробуйте учебный кабинет', 'Команда «ЛатехТим»'],
     'Начните с демо, затем вернитесь в свой кабинет и подготовьте первый лист. ЛистОК объединяет материал, печать, проверку и результаты класса. Спасибо за внимание.'),
]


def font(size, bold=False):
    candidates = [Path('C:/Windows/Fonts/' + ('segoeuib.ttf' if bold else 'segoeui.ttf')),
                  Path('/usr/share/fonts/truetype/dejavu/' + ('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'))]
    return ImageFont.truetype(str(next(p for p in candidates if p.exists())), size)


def wrap(draw, text, face, width):
    lines, line = [], ''
    for word in text.split():
        candidate = (line + ' ' + word).strip()
        if line and draw.textlength(candidate, font=face) > width:
            lines.append(line); line = word
        else:
            line = candidate
    return lines + ([line] if line else [])


def block(draw, text, xy, width, size, color, bold=False, gap=12):
    x, y = xy
    for line in wrap(draw, text, font(size, bold), width):
        draw.text((x, y), line, font=font(size, bold), fill=color)
        y += size + gap
    return y


def frame(index, scene):
    section, title, duration, image_name, layout, points, narration = scene
    bg, ink, purple, quiet = '#F5F4FA', '#202133', '#7551D7', '#666278'
    im = Image.new('RGB', (1920, 1080), bg); d = ImageDraw.Draw(im)
    d.rounded_rectangle((64, 42, 119, 97), radius=15, fill=purple)
    d.line([(78,70),(88,80),(108,58)], fill='white', width=5)
    d.text((136,43),'ЛистОК',font=font(36,True),fill=ink)
    d.text((1660,52),f'{index+1:02d} / {len(SCENES):02d}',font=font(26),fill=quiet)
    d.line((64,1010,1856,1010),fill='#DDDAE7',width=2)
    d.text((64,1030),'Учебные данные · экранная инструкция',font=font(22),fill=quiet)
    d.text((1470,1030),'ЛатехТим · 2026',font=font(22),fill=quiet)
    if layout in ('cover','end'):
        d.text((100,190),'АРСЕНАЛ МАСТЕРА',font=font(27,True),fill=purple)
        block(d,title,(100,280),1550,94,ink,True,18)
        y=590
        for n,p in enumerate(points):
            d.rounded_rectangle((100+n*570,y,640+n*570,y+170),radius=25,fill='white',outline='#E1DCEA',width=2)
            block(d,p,(132+n*570,y+48),475,34,ink,True)
        d.text((100,870),'Математика и физика · учитель, ученик, завуч',font=font(30),fill=quiet)
        return im
    d.text((64,160),section.upper(),font=font(25,True),fill=purple)
    y=block(d,title,(64,215),515,54,ink,True,13)+48
    for n,p in enumerate(points):
        d.rounded_rectangle((66,y+5,101,y+40),radius=10,fill='#E9E2FA')
        d.text((76,y+6),str(n+1),font=font(22,True),fill=purple)
        y=block(d,p,(121,y),440,29,ink,gap=10)+32
    if layout=='chat':
        d.text((64,910),'MAX · чат с ботом проекта',font=font(24),fill=quiet)
    elif layout=='phone':
        d.text((64,910),'Мобильная версия',font=font(24),fill=quiet)
    elif layout=='paper':
        d.text((64,910),'A4 · LaTeX · CMU',font=font(24),fill=quiet)
    else:
        d.text((64,910),'Кабинет учителя · демо',font=font(24),fill=quiet)
    source = Image.open(OUT/'scenes'/image_name).convert('RGB')
    if layout=='screen':
        # Remove empty browser margin, retain the actual application content.
        source=source.crop((380,0,min(1750,source.width),source.height))
    elif layout=='chat':
        source=source.crop((300,0,min(1160,source.width),source.height))
    elif layout=='scan':
        source=source.crop((650,50,1510,source.height))
    box=(630,145,1856,970)
    fitted=ImageOps.contain(source,(box[2]-box[0]-32,box[3]-box[1]-32),Image.Resampling.LANCZOS)
    x=box[0]+(box[2]-box[0]-fitted.width)//2;y=box[1]+(box[3]-box[1]-fitted.height)//2
    d.rounded_rectangle((x-12,y-12,x+fitted.width+12,y+fitted.height+12),radius=24,fill='white',outline='#DFDAEB',width=2)
    im.paste(fitted,(x,y))
    return im


def timecode(seconds):
    return f'{seconds//60:02d}:{seconds%60:02d}'


def build(render=True):
    frames=OUT/'frames';clips=OUT/'clips'
    frames.mkdir(parents=True,exist_ok=True);clips.mkdir(exist_ok=True)
    shutil.copyfile(ROOT/'output/qa/student-autosave-production.png',OUT/'autosave.png')
    elapsed=0;manifest=[]
    script=['# ЛистОК — текст озвучки\n',
            'Видео без голоса; можно записывать каждый абзац отдельно. Читать спокойно, с паузами. '
            'Команды на экране начинаются с `/`; в речи достаточно сказать их названия. '
            'Показаны синтетические данные. Встроенный запуск MAX зависит от привязки организаторами. '
            'Точность голосового режима на живой речи ещё предстоит проверить; в ролике показана справка, '
            'а не отправка настоящего голосового. Эти служебные заметки озвучивать не нужно.\n']
    for i,scene in enumerate(SCENES):
        section,title,duration,_,_,_,narration=scene
        image_path=frames/f'{i+1:02d}.png';frame(i,scene).save(image_path)
        item={'scene':i+1,'title':title,'start':elapsed,'duration':duration,'narration':narration,'frame':image_path.name}
        manifest.append(item)
        script.append(f'## {timecode(elapsed)}–{timecode(elapsed+duration)} · {title}\n\n{narration}\n')
        if render:
            command=['ffmpeg','-hide_banner','-loglevel','error','-y','-loop','1','-framerate','15','-i',str(image_path),
                     '-t',str(duration),'-vf',f'fade=t=in:st=0:d=0.3:color=0xf5f4fa,fade=t=out:st={duration-.3}:d=0.3:color=0xf5f4fa',
                     '-c:v','libx264','-threads','4','-preset','fast','-crf','19','-pix_fmt','yuv420p','-an',str(clips/f'{i+1:02d}.mp4')]
            subprocess.run(command,check=True)
            print(f'{i+1}/{len(SCENES)} {title}',flush=True)
        elapsed+=duration
    (OUT/'narration.md').write_text('\n'.join(script),encoding='utf-8')
    (OUT/'narration.txt').write_text('\n'.join(line.removeprefix('## ').removeprefix('# ') for line in script),encoding='utf-8-sig')
    (OUT/'scenes.json').write_text(json.dumps({'duration':elapsed,'scenes':manifest},ensure_ascii=False,indent=2),encoding='utf-8')
    if render:
        concat=OUT/'concat.txt';concat.write_text(''.join(f"file 'clips/{i+1:02d}.mp4'\n" for i in range(len(SCENES))),encoding='utf-8')
        metadata=OUT/'chapters.txt';lines=[';FFMETADATA1','title=ЛистОК — инструкция','artist=ЛатехТим']
        for item in manifest:
            lines+=['[CHAPTER]','TIMEBASE=1/1000',f"START={item['start']*1000}",f"END={(item['start']+item['duration'])*1000}",f"title={item['title']}"]
        metadata.write_text('\n'.join(lines)+'\n',encoding='utf-8')
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(concat),'-i',str(metadata),
                        '-map_metadata','1','-map_chapters','1','-c','copy','-movflags','+faststart',str(OUT/'listok-guide-silent.mp4')],check=True)
    print(f'Duration: {timecode(elapsed)}; narration and frames saved.',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--frames-only',action='store_true');args=parser.parse_args()
    build(not args.frames_only)

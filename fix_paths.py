import os
import glob

template_dir = r'c:\Users\NeumoinPD\YandexDisk\Latex\Проекты 10С\Проекты\Усик\ИТ проект\проект\templates'
for filepath in glob.glob(os.path.join(template_dir, '*.html')):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Избегаем двойной замены
    content = content.replace('href="/style-muse/', 'href="/')
    content = content.replace('action="/style-muse/', 'action="/')
    
    # Замена на нужный префикс
    content = content.replace('href="/', 'href="/style-muse/')
    content = content.replace('action="/', 'action="/style-muse/')
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
        
print("OK")

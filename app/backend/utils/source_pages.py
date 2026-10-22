"""Decode untrusted uploads only inside the bounded AI worker subprocess.

PDFium must not run concurrently in web threads. No PDF attachments or metadata
are sent to the provider: only bounded, freshly encoded page images.
"""
from pathlib import Path
from contextlib import closing
import math
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError
import pypdfium2 as pdfium

from utils.gigachat_client import AIServiceError

MAX_PAGES = 10
MAX_EDGE = 2200
MAX_IMAGE_PIXELS = 40_000_000


def prepare(paths, directory):
    directory = Path(directory)
    directory.mkdir(exist_ok=True)
    result = []

    def save(image):
        if len(result) >= MAX_PAGES:
            raise AIServiceError('Загрузите не более 10 страниц за один раз.', 'page_limit', 400)
        with image.convert('RGB') as rgb:
            rgb.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
            target = directory / f'page_{len(result) + 1}.jpg'
            # No EXIF, names or embedded PDF content are preserved.
            rgb.save(target, 'JPEG', quality=92)
            result.append(str(target))

    for raw in paths:
        path = Path(raw)
        if path.suffix.lower() == '.pdf':
            try:
                with pdfium.PdfDocument(path) as document:
                    if not 1 <= len(document) <= MAX_PAGES - len(result):
                        raise AIServiceError('В PDF должно быть от 1 до 10 страниц. Сохраните нужный фрагмент отдельным файлом.', 'page_limit', 400)
                    for index in range(len(document)):
                        with closing(document[index]) as page:
                            width, height = page.get_size()
                            if not all(math.isfinite(n) and 1 <= n <= 20000 for n in (width, height)):
                                raise AIServiceError('В PDF некорректный размер страницы.', 'invalid_pdf', 400)
                            scale = min(2.5, MAX_EDGE / max(width, height))
                            with closing(page.render(scale=scale)) as bitmap:
                                with bitmap.to_pil() as image:
                                    save(image)
            except pdfium.PdfiumError as exc:
                raise AIServiceError('Не удалось открыть PDF. Загрузите исправный файл без пароля или фотографии страниц.', 'invalid_pdf', 400) from exc
        else:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('error', Image.DecompressionBombWarning)
                    with Image.open(path) as image:
                        if image.format not in ('JPEG', 'PNG') or image.width * image.height > MAX_IMAGE_PIXELS:
                            raise AIServiceError('Выберите PNG или JPEG размером до 40 мегапикселей.', 'image_limit', 400)
                        if getattr(image, 'n_frames', 1) != 1:
                            raise AIServiceError('Загрузите обычное фото без анимации.', 'invalid_image', 400)
                        with ImageOps.exif_transpose(image) as upright:
                            save(upright)
            except (UnidentifiedImageError, OSError, Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
                raise AIServiceError('Фото повреждено или слишком большое. Сохраните его заново в PNG или JPEG.', 'invalid_image', 400) from exc
    return result

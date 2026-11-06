"""Local QR matching only. A printed marker is not proof of a pupil's identity."""
import io
import re
import qrcode
import zxingcpp
from PIL import Image

PATTERN = re.compile(r'LISTOK1:([A-F0-9]{32}):([A-F0-9]{12}):([A-F0-9]{10})')


def payload(assignment_id, edition_code, student_code):
    text = f'LISTOK1:{assignment_id.upper()}:{edition_code}:{student_code.removeprefix("У-")}'
    if not PATTERN.fullmatch(text):
        raise ValueError('Invalid answer marker')
    return text


def png(assignment_id, edition_code, student_code):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=4)
    qr.add_data(payload(assignment_id, edition_code, student_code)); qr.make(fit=True)
    stream = io.BytesIO(); qr.make_image().save(stream, format='PNG')
    return stream.getvalue()


def read(path):
    with Image.open(path) as image:
        codes = {b.text for b in zxingcpp.read_barcodes(image.convert('RGB'), formats=zxingcpp.BarcodeFormat.QRCode)
                 if b.text.startswith('LISTOK1:')}
    if not codes:
        return {}
    if len(codes) != 1 or not PATTERN.fullmatch(next(iter(codes))):
        return {'student_code': '', 'edition_code': '', 'assignment_code': '',
                'marker_warning': 'QR-метки неоднозначны или повреждены. Сверьте ученика и работу вручную.'}
    assignment, edition, student = PATTERN.fullmatch(next(iter(codes))).groups()
    return {'assignment_code': assignment.lower(), 'edition_code': edition, 'student_code': 'У-' + student}

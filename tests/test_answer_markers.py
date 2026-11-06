import io
import tempfile
from pathlib import Path
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app/backend'))
import qrcode
from PIL import Image
from utils import answer_markers


class AnswerMarkerTests(unittest.TestCase):
    def test_exact_codes_survive_rotation_and_scan_compression(self):
        data = answer_markers.png('a' * 32, '7CF12DDB3F52', 'У-473BBC66B6')
        with tempfile.TemporaryDirectory() as directory:
            for angle in (0, 90, 180):
                path = Path(directory) / f'{angle}.jpg'
                with Image.open(io.BytesIO(data)) as image:
                    image.convert('RGB').rotate(angle, expand=True).save(path, quality=75)
                result = answer_markers.read(path)
                self.assertEqual(result, {'assignment_code': 'a' * 32, 'edition_code': '7CF12DDB3F52', 'student_code': 'У-473BBC66B6'})

    def test_multiple_and_malformed_markers_never_pick_a_pupil(self):
        with tempfile.TemporaryDirectory() as directory:
            one = Image.open(io.BytesIO(answer_markers.png('a'*32, '7CF12DDB3F52', 'У-473BBC66B6'))).convert('RGB')
            two = Image.open(io.BytesIO(answer_markers.png('a'*32, '7CF12DDB3F52', 'У-0123456789'))).convert('RGB')
            both = Image.new('RGB', (one.width + two.width + 30, one.height), 'white')
            both.paste(one); both.paste(two, (one.width+30, 0))
            path = Path(directory)/'both.png'; both.save(path)
            result = answer_markers.read(path)
            self.assertTrue(result['marker_warning']); self.assertEqual(result['student_code'], '')
            qrcode.make('LISTOK1:malformed').save(path)
            self.assertTrue(answer_markers.read(path)['marker_warning'])
            qrcode.make('https://example.com/unrelated').save(path)
            self.assertEqual(answer_markers.read(path), {})

    def test_marker_contains_only_valid_assignment_edition_and_pupil_code(self):
        for args in [('bad', '7CF12DDB3F52', 'У-473BBC66B6'), ('a'*32, 'wrong', 'У-473BBC66B6'), ('a'*32, '7CF12DDB3F52', 'Name')]:
            with self.assertRaises(ValueError): answer_markers.png(*args)

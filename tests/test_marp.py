import sys
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app/backend'))
from utils.marp_export import export_bundle, markdown
from utils.worksheet import demo_worksheet
from utils.gigachat_client import AIServiceError


class MarpTests(unittest.TestCase):
    def test_answer_separation_and_math_preserved(self):
        sheet = demo_worksheet('math')
        student, teacher = markdown(sheet), markdown(sheet, answers=True)
        self.assertNotIn(sheet['tasks'][1]['answer'], student)
        self.assertIn(sheet['tasks'][1]['answer'], teacher)
        self.assertIn('$x^2-5x+6=0$', student)
        self.assertNotIn('answer-space', teacher)

    def test_untrusted_prose_cannot_create_html_images_directives_or_slides(self):
        sheet = demo_worksheet('math')
        sheet['title'] = '<script>alert(1)</script>\n---\n<!-- theme: evil -->'
        sheet['tasks'][0]['question'] = '![image](https://evil.test/a)\n</div><iframe src=x>\n---'
        result = markdown(sheet)
        for unsafe in ('<script>', '<iframe src=', '![image]', '<!-- theme: evil'):
            self.assertNotIn(unsafe,result)
        self.assertEqual(result.count('\n---\n'), 1)  # frontmatter end only
        sheet['tasks'][0]['question'] = r'$\href{https://evil.test}{x}$'
        with self.assertRaises(AIServiceError): markdown(sheet)

    def test_bundle_contains_complete_a4_theme_and_honours_pagination(self):
        sheet = demo_worksheet('physics')
        sheet['settings'] = {'columns':2,'tasks_per_page':2,'field':'blank'}
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory)/'source.zip'
            export_bundle(sheet, archive, {'author':'Учитель','title':'Основа'})
            with ZipFile(archive) as package:
                self.assertEqual(set(package.namelist()), {'worksheet.md','answers.md','listok.css','README.txt'})
                student = package.read('worksheet.md').decode()
                self.assertIn('columns-2 field-blank', student)
                self.assertEqual(student.count('\n---\n'),2)
                self.assertIn('Основа: Учитель',student)
                self.assertIn('height: 297mm',package.read('listok.css').decode())
                self.assertIn('--theme listok.css --html',package.read('README.txt').decode())


if __name__ == '__main__': unittest.main()

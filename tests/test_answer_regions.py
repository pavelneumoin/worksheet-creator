import tempfile
from pathlib import Path
import unittest
from PIL import Image, ImageDraw
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app/backend'))
from utils.answer_regions import grid_boxes


class AnswerRegionsTests(unittest.TestCase):
    def test_grid_includes_task_number_and_every_row(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'form.jpg'
            image=Image.new('RGB',(1000,1414),'white');draw=ImageDraw.Draw(image)
            for y in (300,328,356,384):draw.line((100,y,810,y),fill='#909090',width=2)
            for x in range(100,811,26):draw.line((x,300,x,384),fill='#909090',width=2)
            image.save(path)
            boxes=grid_boxes(path,3)
            self.assertEqual(len(boxes),3)
            self.assertLess(boxes[0][0],100);self.assertGreater(boxes[0][2],810)
            self.assertLess(boxes[1][1],328/1414*1000)
            self.assertGreater(boxes[1][3],356/1414*1000)
            self.assertEqual(grid_boxes(path,4),[])
            draw.text((140,335),'8/10',fill='black')
            image.save(path)
            narrow=grid_boxes(path,3)
            self.assertLess(narrow[1][2],boxes[1][2])
            draw.line((650,336,675,348),fill='black',width=2)
            image.save(path)
            self.assertGreaterEqual(grid_boxes(path,3)[1][2],675)
            image.rotate(10,fillcolor='white').save(path)
            self.assertEqual(grid_boxes(path,3),[])

    def test_text_and_irregular_lines_do_not_propose_a_fragment(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'page.png'
            image=Image.new('RGB',(1000,1414),'white');draw=ImageDraw.Draw(image)
            for y in (300,328,360,410):draw.line((100,y,810,y),fill='#909090',width=2)
            image.save(path)
            self.assertEqual(grid_boxes(path,3),[])

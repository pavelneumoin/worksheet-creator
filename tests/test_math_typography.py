import unittest
from utils.worksheet import rich_text_to_tex
from utils.gigachat_client import AIServiceError


class MathTypographyTests(unittest.TestCase):
    def test_explicit_delimiters_normalize_without_changing_prose(self):
        for source in (r'\(\frac{1}{2}\)',r'\[\frac{1}{2}\]',r'$$\frac{1}{2}$$'):
            self.assertEqual(rich_text_to_tex('Найдите '+source+'.'),r'Найдите $\frac{1}{2}$.')
        self.assertEqual(rich_text_to_tex('Цена 50% & номер_1'),r'Цена 50\% \& номер\_1')

    def test_cyrillic_units_and_decimal_spacing_are_fixed_inside_structured_math(self):
        self.assertEqual(rich_text_to_tex(r'$m=2,5\,кг; a=3\,м/с^2$'),r'$m=2{,}5\,\text{кг}; a=3\,\text{м}/\text{с}^2$')
        self.assertEqual(rich_text_to_tex('$x−2≤3$'),r'$x-2\leq 3$')

    def test_safe_systems_and_matrices_keep_alignment(self):
        value = r'$\begin{cases}x+y=3\\x-y=1\end{cases}$'
        self.assertEqual(rich_text_to_tex(value),value)
        for bad in (r'$\begin{document}x\end{document}$',r'$\begin{cases}x\end{matrix}$',r'$\input{secret}$',r'$\begin{cases}x$',r'$x&y$',r'$x\\y$',r'\frac{1}{2}',r'\(x'):
            with self.subTest(bad=bad),self.assertRaises(AIServiceError):rich_text_to_tex(bad)

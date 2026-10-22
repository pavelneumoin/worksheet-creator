import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app/backend'))
from fractions import Fraction
from utils.arithmetic_check import evaluate, check_numeric_answers, Unsupported


class ArithmeticTests(unittest.TestCase):
    def test_exact_values_and_operator_precedence(self):
        cases = {r'\frac{\frac{3}{4}+\frac{5}{6}}{\frac{7}{12}}':Fraction(19,7),
                 r'\sqrt{81}+\sqrt{16}':Fraction(13), '0,1+0,2':Fraction(3,10),
                 '-2^2':Fraction(-4), '(-2)^2':Fraction(4), '2^{-3}':Fraction(1,8)}
        for formula, expected in cases.items():
            self.assertEqual(evaluate(formula), expected)

    def test_unsupported_expressions_never_execute_or_guess(self):
        for formula in ('x+1', '1/0', '__import__("os")', r'\sqrt{2}', '2^1000000', '2(3+4)', '2 кг', '1+2=3'):
            with self.subTest(formula=formula),self.assertRaises((Unsupported,ZeroDivisionError)):
                evaluate(formula)

    def test_model_error_corrected_only_for_unambiguous_numeric_exercise(self):
        task={'id':'1','question':r'Вычислите значение выражения: $\dfrac{\dfrac{3}{4}+\dfrac{5}{6}}{\dfrac{7}{12}}$.','answer':'2','note':''}
        sheet={'subject':'math','tasks':[task]}
        check_numeric_answers(sheet)
        self.assertEqual(task['answer'],r'$\frac{19}{7}$')
        self.assertIn('точным вычислением',task['note'])
        for question,note in [('Вычислите $2+2$. Округлите до десятков.',''), ('Вычислите $2+2$.','Не уверен в числе')]:
            candidate={**task,'question':question,'answer':'original','note':note}
            check_numeric_answers({'subject':'math','tasks':[candidate]})
            self.assertEqual(candidate['answer'],'original')


if __name__=='__main__':unittest.main()

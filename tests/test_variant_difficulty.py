import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app/backend'))
from utils import structured_ai
from utils.gigachat_client import AIServiceError
from utils.worksheet import demo_worksheet


def response(sheet):
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content=json.dumps(sheet)))])


class VariantDifficultyTests(unittest.TestCase):
    def run_variant(self, difficulty, sheets):
        client = unittest.mock.MagicMock()
        client.__enter__.return_value = client
        client.chat.side_effect = [response(sheet) for sheet in sheets]
        with patch.object(structured_ai, '_create_client', return_value=client):
            result = structured_ai.generate('math', original=demo_worksheet('math'), difficulty=difficulty)
        return result, client

    def cosmetic(self):
        sheet = copy.deepcopy(demo_worksheet('math'))
        sheet['tasks'][0]['question'] = 'Решите уравнение $x^{2}-7x+12=0$.'
        sheet['tasks'][1]['question'] = r'Вычислите $\frac{5}{6}+\frac{7}{8}$. Ответ запишите несократимой дробью.'
        sheet['tasks'][2]['question'] = r'Вычислите $\sqrt{144}-\sqrt{25}$.'
        return sheet

    def test_numeric_only_change_is_allowed_for_same_level(self):
        _, client = self.run_variant('same', [self.cosmetic()])
        self.assertEqual(client.chat.call_count, 1)

    def test_cosmetic_harder_and_easier_are_rejected_after_one_repair(self):
        for level in ('easier', 'harder'):
            with self.subTest(level=level), self.assertRaises(AIServiceError) as error:
                self.run_variant(level, [self.cosmetic(), self.cosmetic()])
            self.assertEqual(error.exception.code, 'ai_difficulty_unchanged')

    def test_repaired_structure_preserves_ids_and_settings(self):
        sheet = self.cosmetic()
        sheet['tasks'][0]['question'] = 'Решите уравнение $(x-1)(x-2)=6$.'
        sheet['tasks'][1]['question'] = r'Вычислите $(\frac{5}{6}+\frac{7}{8}):\frac{2}{3}$. Ответ запишите несократимой дробью.'
        sheet['tasks'][2]['question'] = r'Вычислите $2\cdot(\sqrt{144}-\sqrt{25})$.'
        result, client = self.run_variant('harder', [self.cosmetic(), sheet])
        self.assertEqual(client.chat.call_count, 2)
        self.assertEqual(result['settings'], demo_worksheet('math')['settings'])
        self.assertEqual([t['id'] for t in result['tasks']], [t['id'] for t in demo_worksheet('math')['tasks']])
        self.assertEqual(result['tasks'][2]['answer'], '$14$')

    def test_simple_formatting_and_operator_swaps_do_not_hide_cosmetic_change(self):
        self.assertEqual(structured_ai.variant_shape(r'Вычислите $\dfrac{3}{4}+\dfrac{5}{6}$.'),
                         structured_ai.variant_shape(r'Вычислите $\frac{7}{8}-\frac{1}{2}$.'))

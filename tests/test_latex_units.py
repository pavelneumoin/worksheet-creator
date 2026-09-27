"""Regressions for Cyrillic units and silent missing-glyph PDF failures."""
from pathlib import Path
import importlib.util
import subprocess
import tempfile
import unittest
from unittest.mock import patch


def load_module(name, relative):
    path = Path(__file__).resolve().parents[1] / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = load_module("unit_adapter_under_test", "app/backend/utils/gigachat_client.py")
latex = load_module("glyph_compiler_under_test", "app/backend/utils/latex.py")


class CyrillicUnitTests(unittest.TestCase):
    def test_numeric_values_signs_and_units_are_preserved(self):
        source = r"$m=2\,кг; a=3\,м/с^2; F=6\,Н$"
        expected = r"$m=2\,\text{кг}; a=3\,\text{м}/\text{с}^2; F=6\,\text{Н}$"
        self.assertEqual(adapter.normalize_cyrillic_units(source), expected)

    def test_nested_text_groups_are_preserved(self):
        source = r"$\text{Условие {кг}, \{м\}}+\frac{6\,Н}{\text{кг}}$"
        expected = r"$\text{Условие {кг}, \{м\}}+\frac{6\,\text{Н}}{\text{кг}}$"
        self.assertEqual(adapter.normalize_cyrillic_units(source), expected)

    def test_normalization_is_idempotent(self):
        source = r"\TaskBox{1}{Дано $m=2\,кг$ и $a=3\,м/с^2$.}"
        normalized = adapter.clean_latex(source)
        self.assertEqual(adapter.clean_latex(normalized), normalized)

    def test_plain_text_escaped_dollars_and_comments_unchanged(self):
        source = "кг вне формулы; \\$5; % $2кг$ комментарий\n$2кг$"
        expected = "кг вне формулы; \\$5; % $2кг$ комментарий\n$2\\text{кг}$"
        self.assertEqual(adapter.normalize_cyrillic_units(source), expected)

    def test_display_and_environment_math(self):
        for before, after in (
            (r"\(6\,Н\)", r"\(6\,\text{Н}\)"),
            (r"\[4\,Дж\]", r"\[4\,\text{Дж}\]"),
            (r"$$2\,А$$", r"$$2\,\text{А}$$"),
            (r"\begin{align*}I&=2\,А\end{align*}",
             r"\begin{align*}I&=2\,\text{А}\end{align*}"),
        ):
            with self.subTest(source=before):
                self.assertEqual(adapter.normalize_cyrillic_units(before), after)

    def test_unknown_words_and_unclosed_math_are_not_guessed(self):
        self.assertEqual(adapter.normalize_cyrillic_units(r"$скорость=5$"), r"$скорость=5$")
        self.assertEqual(adapter.normalize_cyrillic_units(r"Условие $2\,кг"), r"Условие $2\,кг")

    def test_missing_glyph_rejects_otherwise_successful_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            def fake_run(command, cwd, **kwargs):
                Path(cwd, "document.pdf").write_bytes(b"%PDF-1.4\n" + b"x" * 200)
                return subprocess.CompletedProcess(command, 0, stdout=b"Missing character: There is no unit glyph in font\n")
            with patch.object(latex, "OUTPUT_DIR", str(output)), \
                 patch.object(latex, "get_latex_compiler", return_value="xelatex"), \
                 patch.object(latex.subprocess, "run", side_effect=fake_run):
                pdf, error = latex.compile_latex_local("source", "glyph_failure")
            self.assertIsNone(pdf)
            self.assertIn("PDF не выдан", error)
            self.assertFalse((output / "glyph_failure.pdf").exists())

    def test_normal_compiler_success_is_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            def fake_run(command, cwd, **kwargs):
                Path(cwd, "document.pdf").write_bytes(b"%PDF-1.4\n" + b"x" * 200)
                return subprocess.CompletedProcess(command, 0, stdout=b"Output written on document.pdf\n")
            with patch.object(latex, "OUTPUT_DIR", str(output)), \
                 patch.object(latex, "get_latex_compiler", return_value="xelatex"), \
                 patch.object(latex.subprocess, "run", side_effect=fake_run):
                pdf, error = latex.compile_latex_local("source", "valid")
            self.assertEqual(pdf, "valid.pdf")
            self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()

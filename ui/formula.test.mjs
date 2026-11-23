import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import katex from "katex";
import {FORMULAS, isInsideMath, prepareInsertion, stripMathDelimiters} from "./formula.mjs";

test("all templates produce valid LaTeX including Cyrillic-independent math", () => {
  for (const template of FORMULAS) {
    const formula = template.build(template.fields.map(field => field[1]));
    assert.doesNotThrow(() => katex.renderToString(formula, {throwOnError: true, trust: false}));
  }
});
test("inserts a formula in prose without joining adjacent words", () => {
  assert.equal(prepareInsertion("Найдитеответ", 7, 7, "\\frac{1}{2}"), " $\\frac{1}{2}$ ");
  assert.equal(prepareInsertion("Ответ: .", 7, 7, "x^2"), "$x^2$");
  assert.equal(prepareInsertion("заменить", 0, 8, "x"), "$x$");
});
test("inside existing math it does not create nested math delimiters", () => {
  assert.equal(prepareInsertion("$x + y$", 5, 6, "\\sqrt{a}"), "\\sqrt{a}");
  assert.equal(isInsideMath("\\(x + y\\)", 6), true);
  assert.equal(isInsideMath("\\[x + y\\]", 6), true);
  assert.equal(isInsideMath("$$x + y$$", 6), true);
  assert.equal(isInsideMath("$x$ = ответ", 5), false);
  assert.equal(isInsideMath("Цена \\$5", 8), false);
});
test("selected math can be reused as a numerator without double dollars", () => {
  assert.equal(stripMathDelimiters("$x + 1$"), "x + 1");
  assert.equal(stripMathDelimiters("\\(x+1\\)"), "x+1");
  assert.equal(stripMathDelimiters("$$x+1$$"), "x+1");
  assert.equal(stripMathDelimiters("x+1"), "x+1");
});
test("inserting symbols next to a variable keeps TeX commands separate", () => {
  for (const [text, caret, value, result] of [
    ["$x$", 1, "\\pi", "\\pi x"],
    ["$\\alpha$", 7, "b", "\\alpha b"],
  ]) {
    const addition = prepareInsertion(text, caret, caret, value);
    const equation = (text.slice(0, caret) + addition + text.slice(caret)).slice(1, -1);
    assert.equal(equation, result);
    assert.doesNotThrow(() => katex.renderToString(equation, {throwOnError: true}));
  }
});
test("legacy insertion preserves selection, input notification, and maxlength", () => {
  const context = {module: {exports: {}}, Event};
  vm.runInNewContext(fs.readFileSync(new URL("../app/frontend/latex_keyboard.js", import.meta.url), "utf8"), context);
  const {insertLatexSnippet} = context.module.exports;
  const textarea = {value: "abXcd", selectionStart: 2, selectionEnd: 3, maxLength: 20, setSelectionRange(a, b) { this.selectionStart = a; this.selectionEnd = b; }, dispatchEvent(event) { this.input = event.type; }, focus() { this.focused = true; }};
  assert.equal(insertLatexSnippet(textarea, "a^{2}", "2"), true);
  assert.equal(textarea.value, "aba^{2}cd");
  assert.equal(textarea.selectionStart, 5);
  assert.equal(textarea.selectionEnd, 6);
  assert.equal(textarea.input, "input");
  assert.equal(textarea.focused, true);
  const original = textarea.value;
  assert.equal(insertLatexSnippet(textarea, "x".repeat(21)), false);
  assert.equal(textarea.value, original);
});

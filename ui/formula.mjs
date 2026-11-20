// Formula composition is shared by the UI and the cursor/insertion tests.
export const FORMULAS = [
  {id: "fraction", name: "Дробь", example: "\\frac{a}{b}", fields: [["Числитель", "a"], ["Знаменатель", "b"]], build: ([a, b]) => `\\frac{${a}}{${b}}`},
  {id: "power", name: "Степень", example: "x^{2}", fields: [["Основание", "x"], ["Степень", "2"]], build: ([a, b]) => `{${a}}^{${b}}`},
  {id: "root", name: "Корень", example: "\\sqrt{x}", fields: [["Под корнем", "x"]], build: ([a]) => `\\sqrt{${a}}`},
  {id: "index", name: "Индекс", example: "a_{1}", fields: [["Основание", "a"], ["Индекс", "1"]], build: ([a, b]) => `{${a}}_{${b}}`},
  {id: "log", name: "Логарифм", example: "\\log_{a}x", fields: [["Основание", "2"], ["Аргумент", "x"]], build: ([a, b]) => `\\log_{${a}}\\left(${b}\\right)`},
  {id: "formula", name: "Своя формула", example: "f(x)", fields: [["Формула LaTeX", "x^2 + 3x - 4 = 0"]], build: ([a]) => a},
];

export const SYMBOLS = [
  ["\\pm", "Плюс-минус"], ["\\cdot", "Умножение"], ["\\div", "Деление"],
  ["\\leq", "Меньше или равно"], ["\\geq", "Больше или равно"], ["\\neq", "Не равно"],
  ["\\pi", "Число пи"], ["\\alpha", "Альфа"], ["\\beta", "Бета"],
  ["\\infty", "Бесконечность"], ["\\sin x", "Синус"], ["\\cos x", "Косинус"],
];

export function stripMathDelimiters(value) {
  return value.trim().replace(/^(?:\$\$([\s\S]*)\$\$|\$([\s\S]*)\$|\\\(([\s\S]*)\\\)|\\\[([\s\S]*)\\\])$/, (_match, ...groups) => groups.slice(0, 4).find(x => x !== undefined) ?? "");
}

export function isInsideMath(text, position) {
  const before = text.slice(0, position);
  let open = null;
  const tokens = /(?<!\\)(?:\$\$|\$)|\\[()[\]]/g;
  for (const token of before.matchAll(tokens)) {
    const t = token[0];
    if (t === "$" || t === "$$") {
      if (!open) open = t;
      else if (open === t) open = null;
    } else if (t === "\\(" || t === "\\[") {
      if (!open) open = t;
    } else if ((t === "\\)" && open === "\\(") || (t === "\\]" && open === "\\[")) open = null;
  }
  return open !== null;
}

export function prepareInsertion(text, start, end, latex) {
  const raw = stripMathDelimiters(latex);
  if (isInsideMath(text, start)) return raw;
  const before = text.slice(0, start);
  const after = text.slice(end);
  const leading = before && !/[\s([{]$/.test(before) ? " " : "";
  const trailing = after && !/^[\s.,;:!?)}\]]/.test(after) ? " " : "";
  return `${leading}$${raw}$${trailing}`;
}

export function getSelectedExpression(textarea) {
  return stripMathDelimiters(textarea.value.slice(textarea.selectionStart, textarea.selectionEnd)).slice(0, 500);
}

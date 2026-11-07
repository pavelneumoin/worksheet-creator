"use strict";
function insertLatexSnippet(textarea, value, cursorToken = "") {
  const start = textarea.selectionStart ?? textarea.value.length;
  const end = textarea.selectionEnd ?? start;
  const before = textarea.value.slice(0, start), after = textarea.value.slice(end);
  const tokenIndex = cursorToken ? value.indexOf(cursorToken) : -1;
  textarea.value = before + value + after;
  const cursor = tokenIndex >= 0 ? start + tokenIndex : start + value.length;
  textarea.setSelectionRange(cursor, cursor + (tokenIndex >= 0 ? cursorToken.length : 0));
  textarea.dispatchEvent(new Event("input", {bubbles:true}));
  textarea.focus();
}
function initLatexKeyboard() {
  const textarea = $("sourceText");
  if (!textarea) return;
  document.querySelectorAll("#latexKeyboard [data-latex]").forEach(button => {
    button.addEventListener("click", () => insertLatexSnippet(textarea, button.dataset.latex, button.dataset.cursor || ""));
  });
}
initLatexKeyboard();
if (typeof module !== "undefined") module.exports = {insertLatexSnippet};

import React, {useEffect, useMemo, useRef, useState, Component} from "react";
import {createRoot} from "react-dom/client";
import {Button} from "@astryxdesign/core/Button";
import {SegmentedControl, SegmentedControlItem} from "@astryxdesign/core/SegmentedControl";
import {TextInput} from "@astryxdesign/core/TextInput";
import {ThemeContext} from "@astryxdesign/core/theme";
import {neutralTheme} from "@astryxdesign/theme-neutral/built";
import {FORMULAS, SYMBOLS, getSelectedExpression, prepareInsertion} from "./formula.mjs";

// A local provider deliberately leaves the host page's theme and typography alone.
// All prebuilt Astryx CSS is scoped by scripts/build_ui.mjs to these islands.
const THEME_CONTEXT = {theme: neutralTheme, mode: "light"};
function IslandTheme({children}) {
  return <ThemeContext value={THEME_CONTEXT}><div className="listok-astryx-theme" data-astryx-theme="neutral" data-theme="light">{children}</div></ThemeContext>;
}

function FormulaPreview({latex, className = "", onValidity}) {
  const element = useRef(null);
  useEffect(() => {
    let valid = true;
    try {
      if (window.katex) window.katex.render(latex, element.current, {throwOnError: true, trust: false, strict: "ignore", output: "htmlAndMathml", maxExpand: 100, maxSize: 12});
      else element.current.textContent = latex;
    } catch {
      element.current.textContent = "Проверьте запись формулы";
      valid = false;
    }
    onValidity?.(valid);
  }, [latex, onValidity]);
  return <span ref={element} className={`listok-formula-preview ${className}`} />;
}

function FormulaKeyboard({textarea}) {
  const [mode, setMode] = useState("templates");
  const [templateId, setTemplateId] = useState(null);
  const [values, setValues] = useState([]);
  const [valid, setValid] = useState(true);
  const [message, setMessage] = useState("");
  const selection = useRef({start: textarea.selectionStart || 0, end: textarea.selectionEnd || 0});
  const template = FORMULAS.find(item => item.id === templateId);
  const latex = useMemo(() => template ? template.build(values.map(value => value.trim())) : "", [template, values]);
  useEffect(() => {
    const remember = () => { selection.current = {start: textarea.selectionStart ?? textarea.value.length, end: textarea.selectionEnd ?? textarea.value.length}; };
    const events = ["select", "keyup", "click", "input", "focus", "blur"];
    events.forEach(event => textarea.addEventListener(event, remember));
    return () => events.forEach(event => textarea.removeEventListener(event, remember));
  }, [textarea]);
  function chooseTemplate(item) {
    setTemplateId(item.id);
    const defaults = item.fields.map(field => field[1]);
    const selected = getSelectedExpression(textarea);
    if (selected) defaults[0] = selected;
    setValues(defaults);
    setMessage("");
    setValid(true);
  }
  function insert(value) {
    const start = Math.min(selection.current.start, textarea.value.length);
    const end = Math.min(selection.current.end, textarea.value.length);
    const addition = prepareInsertion(textarea.value, start, end, value);
    textarea.setSelectionRange(start, end);
    if (typeof window.insertLatexSnippet !== "function") return;
    const inserted = window.insertLatexSnippet(textarea, addition);
    if (inserted === false) {
      setMessage("Не хватает места: сократите текст задания.");
      return;
    }
    selection.current = {start: textarea.selectionStart, end: textarea.selectionEnd};
    setMessage("Формула добавлена в текст");
    setTemplateId(null);
  }
  return <section className="listok-formula" aria-label="Математический редактор">
    <div className="listok-formula-top">
      <span className="listok-formula-title"><span aria-hidden="true">ƒ</span> Формулы</span>
      <SegmentedControl label="Режим математического редактора" value={mode} onChange={value => { setMode(value); setTemplateId(null); setMessage(""); }} size="sm">
        <SegmentedControlItem value="templates" label="Шаблоны" />
        <SegmentedControlItem value="symbols" label="Знаки" />
      </SegmentedControl>
    </div>
    {mode === "templates" ? <div className="listok-formula-grid">
      {FORMULAS.map(item => <Button key={item.id} label={item.name} variant="secondary" aria-pressed={templateId === item.id} onClick={() => chooseTemplate(item)}>
        <span className="listok-formula-key"><FormulaPreview latex={item.example} /><span>{item.name}</span></span>
      </Button>)}
    </div> : <div className="listok-symbol-grid">
      {SYMBOLS.map(([value, label]) => <Button key={value} label={label} variant="secondary" onClick={() => insert(value)}><FormulaPreview latex={value} /></Button>)}
    </div>}
    {template && <div className="listok-formula-composer">
      <div className="listok-formula-composer-title"><strong>{template.name}</strong><Button label="Закрыть редактор формулы" variant="ghost" isIconOnly icon={<span aria-hidden="true">×</span>} size="sm" onClick={() => setTemplateId(null)} /></div>
      <div className={`listok-formula-fields ${template.fields.length === 1 ? "is-single" : ""}`}>
        {template.fields.map(([label], index) => <TextInput key={`${template.id}-${index}`} label={label} value={values[index] || ""} onChange={value => setValues(current => current.map((v, i) => i === index ? value.slice(0, 500) : v))} onEnter={() => { if (valid && values.every(value => value.trim())) insert(latex); }} autoComplete="off" autoCapitalize="off" hasAutoCorrect={false} hasSpellCheck={false} enterKeyHint="done" size="md" />)}
      </div>
      <div className="listok-formula-composer-footer"><div className={`listok-formula-result ${!valid ? "has-error" : ""}`} aria-label="Предпросмотр формулы"><FormulaPreview latex={latex} onValidity={setValid} /></div><Button label="Вставить" variant="primary" onClick={() => insert(latex)} isDisabled={!valid || values.some(value => !value.trim())} /></div>
    </div>}
    <span className="listok-formula-status" role="status" aria-live="polite">{message}</span>
  </section>;
}

function VariantPicker({select, onReady}) {
  const [value, setValue] = useState(select.value || "1");
  useEffect(() => {
    onReady();
    const sync = () => setValue(select.value || "1");
    const reset = () => queueMicrotask(sync);
    select.addEventListener("change", sync);
    select.form?.addEventListener("reset", reset);
    return () => { select.removeEventListener("change", sync); select.form?.removeEventListener("reset", reset); };
  }, [select]);
  function change(next) {
    select.value = next;
    select.dispatchEvent(new Event("input", {bubbles: true}));
    select.dispatchEvent(new Event("change", {bubbles: true}));
    setValue(next);
  }
  return <div className="listok-variants"><SegmentedControl label="Количество вариантов" value={value} onChange={change} layout="fill" size="md">
    {["1", "2", "3", "4"].map(number => <SegmentedControlItem key={number} value={number} label={number} />)}
  </SegmentedControl><span className="listok-variants-description">{value === "1" ? "По исходному материалу" : `Исходный + ${Number(value) - 1} ${value === "2" ? "аналогичный" : "аналогичных"}`}</span></div>;
}

class IslandBoundary extends Component {
  state = {failed: false};
  static getDerivedStateFromError() { return {failed: true}; }
  componentDidCatch(error) { console.error("ListOK editor could not start", error); queueMicrotask(this.props.restore); }
  render() { return this.state.failed ? null : this.props.children; }
}

function mountIslands() {
  const keyboard = document.getElementById("latexKeyboard");
  const textarea = document.getElementById("sourceText");
  if (keyboard && textarea && !keyboard.dataset.listokAstryx) {
    const original = keyboard.innerHTML;
    keyboard.dataset.listokAstryx = "formula";
    keyboard.classList.add("latex-keyboard--astryx");
    const root = createRoot(keyboard);
    const restore = () => {
      root.unmount();
      keyboard.innerHTML = original;
      keyboard.classList.remove("latex-keyboard--astryx");
      delete keyboard.dataset.listokAstryx;
      window.initLatexKeyboard?.();
    };
    root.render(<IslandBoundary restore={restore}><IslandTheme><FormulaKeyboard textarea={textarea} /></IslandTheme></IslandBoundary>);
  }
  const select = document.getElementById("setupVariants");
  if (select && !document.getElementById("listokVariantPicker")) {
    const mount = document.createElement("div");
    mount.id = "listokVariantPicker";
    mount.dataset.listokAstryx = "variants";
    // Keep interactive controls outside the select's wrapping label.
    const label = select.closest("label");
    (label || select).insertAdjacentElement("afterend", mount);
    const root = createRoot(mount);
    const restore = () => { root.unmount(); mount.remove(); select.hidden = false; };
    const ready = () => { select.hidden = true; if (label) { label.classList.add("listok-variant-label"); label.htmlFor = "setupVariants"; } };
    root.render(<IslandBoundary restore={restore}><IslandTheme><VariantPicker select={select} onReady={ready} /></IslandTheme></IslandBoundary>);
  }
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mountIslands, {once: true});
else mountIslands();

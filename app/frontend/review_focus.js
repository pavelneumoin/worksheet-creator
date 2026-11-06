"use strict";

function reviewNeedsAttention(answer) {
  if (answer.score === null || answer.score === undefined) return true;
  if (answer.checked === true) return false;
  return answer.state !== "readable" || answer.comparison !== "matches" ||
    answer.score !== 1 || answer.teacher_edited === true;
}
function reviewBox(box) {
  return Array.isArray(box) && box.length === 4 &&
    box.every(v => Number.isFinite(v) && v >= 0 && v <= 1000) &&
    box[2] > box[0] && box[3] > box[1] ? box : null;
}
function reviewScoreLabel(value) {
  return value === null ? "Не оценено" : Number(value).toLocaleString("ru-RU");
}

// One image is loaded at a time, from the existing owner-only photo endpoint.
// Coordinates are optional OCR hints: the full original always remains accessible.
function openReviewScan(review, answer, number) {
  if (!review.photos.length) return notice("Срок хранения сканов истёк.", true);
  const dialog = node("dialog", undefined, "scan-dialog");
  dialog.setAttribute("aria-label", "Скан · задание " + number);
  const header = node("div", undefined, "scan-dialog-header");
  const title = node("strong", "Задание " + number);
  const close = classButton("Готово", () => dialog.close(), "primary");
  header.append(title, close);
  const source = answer.sources?.find(s => Number.isInteger(s.photo_index) && review.photos[s.photo_index]);
  const pages = node("select"); pages.setAttribute("aria-label", "Страница скана");
  review.photos.forEach((url, index) => {
    const option = node("option", "Страница " + (index + 1)); option.value = index; pages.append(option);
  });
  pages.value = source?.photo_index ?? 0;
  const viewport = node("div", undefined, "scan-viewport");
  viewport.tabIndex = 0;
  viewport.setAttribute("role", "region");
  viewport.setAttribute("aria-label", "Скан. Перемещайте пальцем; масштаб — кнопками или двумя пальцами.");
  const img = node("img"); img.draggable = false; img.alt = "Оригинал работы ученика";
  const hint = node("p", "Перемещайте скан пальцем. Разведите два пальца для увеличения.", "quiet scan-hint");
  const status = node("span", "Загрузка…", "scan-scale"); status.setAttribute("aria-live", "polite");
  const tools = node("div", undefined, "scan-tools");
  let scale = 1, fit = 1, x = 0, y = 0, loaded = false;
  const pointers = new Map();
  const clamp = () => {
    const width = img.naturalWidth * scale, height = img.naturalHeight * scale;
    x = width <= viewport.clientWidth ? (viewport.clientWidth - width) / 2 : Math.min(viewport.clientWidth / 2, Math.max(viewport.clientWidth / 2 - width, x));
    y = height <= viewport.clientHeight ? (viewport.clientHeight - height) / 2 : Math.min(viewport.clientHeight / 2, Math.max(viewport.clientHeight / 2 - height, y));
  };
  const draw = () => {
    if (!loaded) return;
    clamp(); img.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
    status.textContent = Math.round(scale / fit * 100) + "%";
    minus.disabled = scale <= fit * 1.001; plus.disabled = scale >= fit * 8;
  };
  const zoom = (factor, cx = viewport.clientWidth / 2, cy = viewport.clientHeight / 2) => {
    if (!loaded) return;
    const next = Math.max(fit, Math.min(fit * 8, scale * factor));
    x = cx - (cx - x) * next / scale; y = cy - (cy - y) * next / scale; scale = next; draw();
  };
  const full = () => {
    if (!loaded) return;
    fit = Math.min(viewport.clientWidth / img.naturalWidth, viewport.clientHeight / img.naturalHeight);
    scale = fit; x = y = 0; draw();
  };
  const fragment = () => {
    if (!loaded) return;
    full();
    const current = answer.sources?.find(s => s.photo_index === Number(pages.value) && reviewBox(s.box));
    const box = reviewBox(current?.box);
    if (!box) {
      zoom(2); hint.textContent = "Фрагмент не определён. Найдите ответ на полной странице и увеличьте его."; return;
    }
    const bw = (box[2] - box[0]) / 1000 * img.naturalWidth;
    const bh = (box[3] - box[1]) / 1000 * img.naturalHeight;
    scale = Math.max(fit, Math.min(fit * 8, (viewport.clientWidth - 32) / bw, (viewport.clientHeight - 40) / bh));
    x = viewport.clientWidth / 2 - (box[0] + box[2]) / 2000 * img.naturalWidth * scale;
    y = viewport.clientHeight / 2 - (box[1] + box[3]) / 2000 * img.naturalHeight * scale;
    hint.textContent = "Область определена по скану. Если ответ вне кадра — откройте «Весь лист».";
    draw();
  };
  const minus = classButton("−", () => zoom(1 / 1.5)); minus.setAttribute("aria-label", "Уменьшить скан");
  const plus = classButton("+", () => zoom(1.5)); plus.setAttribute("aria-label", "Увеличить скан");
  tools.append(minus, status, plus, classButton("Весь лист", full, "ghost"), classButton("К ответу", fragment, "ghost"));
  viewport.append(img); dialog.append(header, pages, viewport, tools, hint); document.body.append(dialog);
  const load = () => { loaded = false; img.hidden = true; status.textContent = "Загрузка…"; pointers.clear(); img.src = review.photos[Number(pages.value)]; };
  img.addEventListener("load", () => { loaded = true; img.hidden = false; fragment(); });
  img.addEventListener("error", () => { loaded = false; status.textContent = "Нет скана"; hint.textContent = "Не удалось открыть скан. Проверьте соединение или срок хранения; оценки сохранены отдельно."; });
  pages.addEventListener("change", load);
  viewport.addEventListener("pointerdown", e => {
    if (!loaded || e.button > 0) return;
    viewport.setPointerCapture(e.pointerId); pointers.set(e.pointerId, {x:e.clientX, y:e.clientY});
  });
  viewport.addEventListener("pointermove", e => {
    const old = pointers.get(e.pointerId); if (!old) return;
    const other = [...pointers.entries()].find(([id]) => id !== e.pointerId)?.[1];
    if (other) {
      const before = Math.hypot(old.x - other.x, old.y - other.y);
      const after = Math.hypot(e.clientX - other.x, e.clientY - other.y);
      const rect = viewport.getBoundingClientRect();
      if (before > 5) zoom(after / before, (old.x + other.x) / 2 - rect.left, (old.y + other.y) / 2 - rect.top);
      x += (e.clientX - old.x) / 2; y += (e.clientY - old.y) / 2;
    } else { x += e.clientX - old.x; y += e.clientY - old.y; }
    pointers.set(e.pointerId, {x:e.clientX, y:e.clientY}); draw();
  });
  for (const event of ["pointerup", "pointercancel", "lostpointercapture"]) viewport.addEventListener(event, e => pointers.delete(e.pointerId));
  viewport.addEventListener("dblclick", e => { const rect = viewport.getBoundingClientRect(); zoom(2, e.clientX - rect.left, e.clientY - rect.top); });
  viewport.addEventListener("keydown", e => {
    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "+", "-"].includes(e.key)) return;
    e.preventDefault();
    if (e.key === "+" || e.key === "-") zoom(e.key === "+" ? 1.5 : 1 / 1.5);
    else { x += e.key === "ArrowLeft" ? 60 : e.key === "ArrowRight" ? -60 : 0; y += e.key === "ArrowUp" ? 60 : e.key === "ArrowDown" ? -60 : 0; draw(); }
  });
  const resize = new ResizeObserver(() => { if (loaded) fragment(); }); resize.observe(viewport);
  const oldOverflow = document.body.style.overflow; document.body.style.overflow = "hidden";
  dialog.addEventListener("close", () => { resize.disconnect(); document.body.style.overflow = oldOverflow; dialog.remove(); }, {once:true});
  dialog.showModal(); load();
}

function mountReviewFocus(form, fields, controls, review, refreshTotal) {
  const liveAnswer = f => ({...f.answer, checked:f.checked, score:f.score.value === "" ? null : Number(f.score.value), teacher_edited:f.edited || f.answer.teacher_edited});
  let mode = "attention", current = 0;
  const attention = () => fields.map((f, i) => reviewNeedsAttention(liveAnswer(f)) ? i : -1).filter(i => i >= 0);
  if (!attention().length) mode = "all";
  const indices = () => mode === "attention" ? attention() : fields.map((f, i) => i);
  const toolbar = node("section", undefined, "review-focus-toolbar");
  const filters = node("div", undefined, "review-focus-filters"); filters.setAttribute("aria-label", "Показать ответы");
  const counter = node("p", undefined, "quiet review-focus-counter"); counter.setAttribute("aria-live", "polite");
  const picker = node("select"); picker.setAttribute("aria-label", "Перейти к заданию");
  const empty = node("section", undefined, "panel review-focus-empty");
  empty.append(node("h3", "Сомнительные ответы разобраны"), node("p", "Проверьте остальные ответы при необходимости и подтвердите итог работы."));
  const nav = node("div", undefined, "review-focus-nav");
  const move = delta => {
    const list = indices(), pos = list.indexOf(current);
    show(list[Math.max(0, Math.min(list.length - 1, pos + delta))] ?? -1, true);
  };
  const prev = classButton("←", () => move(-1)); prev.setAttribute("aria-label", "Предыдущее задание");
  const next = classButton("→", () => move(1)); next.setAttribute("aria-label", "Следующее задание");
  const done = classButton("Проверено, дальше", () => {
    const field = fields[current]; if (!field || field.score.value === "") return;
    field.checked = true; editReviewDraft(); refreshTotal();
    const list = indices();
    show(mode === "attention" ? (list.find(i => i > current) ?? list[0] ?? -1) : Math.min(current + 1, fields.length - 1), true);
  }, "primary");
  const chooseMode = value => { mode = value; show(indices()[0] ?? -1, true); };
  const uncertain = classButton("Нужно внимание", () => chooseMode("attention"));
  const all = classButton("Все ответы", () => chooseMode("all"));
  const finish = classButton("К итогам работы", () => { controls.scrollIntoView({block:"start", behavior:"smooth"}); controls.querySelector("textarea")?.focus({preventScroll:true}); }, "primary");
  empty.append(classButton("Посмотреть все ответы", () => chooseMode("all")), finish);
  filters.append(uncertain, all); toolbar.append(filters, picker, counter);
  form.querySelector("h2").after(toolbar); controls.before(empty, nav); nav.append(prev, done, next);
  function update() {
    const list = indices();
    uncertain.textContent = "Нужно внимание · " + attention().length; all.textContent = "Все · " + fields.length;
    for (const [button, value] of [[uncertain,"attention"],[all,"all"]]) { button.classList.toggle("active", mode === value); button.setAttribute("aria-pressed", String(mode === value)); }
    picker.replaceChildren();
    for (const i of list) { const option = node("option", "Задание " + (i + 1) + (fields[i].checked ? " · проверено" : "")); option.value = i; picker.append(option); }
    picker.value = String(current); picker.hidden = !list.length;
    counter.textContent = current >= 0 ? `Задание ${current + 1} из ${fields.length} · ${mode === "attention" ? "показываем только требующие внимания" : "все ответы"}` : "Совпадения с ключом не подтверждаются автоматически.";
    prev.disabled = list.indexOf(current) <= 0; next.disabled = list.indexOf(current) >= list.length - 1;
    done.disabled = !fields[current] || fields[current].score.value === "";
    nav.hidden = current < 0; empty.hidden = current >= 0;
  }
  function show(index, scroll = false) {
    current = index; fields.forEach((f,i) => { f.card.hidden = i !== index; }); update();
    if (scroll) { toolbar.scrollIntoView({block:"start", behavior:"smooth"}); (fields[index]?.card.querySelector("h3") || empty.querySelector("h3")).focus({preventScroll:true}); }
  }
  for (const f of fields) {
    f.card.querySelector("h3").tabIndex = -1;
    f.score.addEventListener("change", update); f.text.addEventListener("input", update);
  }
  empty.querySelector("h3").tabIndex = -1;
  picker.addEventListener("change", () => show(Number(picker.value), true));
  show(indices()[0] ?? -1);
}

if (typeof module !== "undefined") module.exports = {reviewNeedsAttention, reviewBox, reviewScoreLabel};

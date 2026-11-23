"use strict";

const analyticsState = {report: null, insight: null};
for (const [name, label, path] of [
  ["analytics", "Статистика", "M4 20V10h4v10M10 20V4h4v16M16 20v-8h4v8"],
  ["school", "Моя школа", "M3 21V7l9-4 9 4v14M8 21v-7h8v7M7 8h2M15 8h2M7 11h2M15 11h2"]
]) {
  const section = node("section");
  section.id = name + "View";
  section.hidden = true;
  document.querySelector("main").append(section);
  const button = node("button", label, "nav-button");
  button.id = name + "Nav";
  button.prepend(studioIcon(path));
  document.querySelector(".topbar nav").append(button);
  button.addEventListener("click", () => busy("Открываем раздел", () => name === "school" ? openSchool() : openAnalytics()));
}

function percentage(value) {
  return value === null || value === undefined ? "—" : value.toLocaleString("ru-RU") + "%";
}

function analyticsTone(value) {
  return value === null || value === undefined ? "neutral" : value < 40 ? "low" : value < 70 ? "middle" : "high";
}

function analyticsDate(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value || "") ? value.split("-").reverse().join(".") : value || "Без даты";
}

function analyticStat(label, value, caption, kind = "") {
  const card = node("div", undefined, "metric-card " + kind);
  card.append(node("span", label, "metric-label"), node("strong", value), node("small", caption));
  return card;
}

function analyticsTable(headers, rows, caption) {
  const wrap = node("div", undefined, "table-wrap analytics-table");
  const table = node("table"), head = node("thead"), heading = node("tr"), body = node("tbody");
  table.setAttribute("role", "table");
  head.setAttribute("role", "rowgroup");
  body.setAttribute("role", "rowgroup");
  heading.setAttribute("role", "row");
  if (caption) table.append(node("caption", caption, "analytics-sr-only"));
  headers.forEach(text => {
    const cell = node("th", text);
    cell.scope = "col";
    cell.setAttribute("role", "columnheader");
    heading.append(cell);
  });
  head.append(heading);
  for (const values of rows) {
    const row = node("tr");
    row.setAttribute("role", "row");
    values.forEach((value, index) => {
      const cell = node("td");
      cell.setAttribute("role", "cell");
      cell.dataset.label = headers[index];
      if (value instanceof Node) cell.append(value);
      else cell.textContent = value ?? "—";
      row.append(cell);
    });
    body.append(row);
  }
  table.append(head, body);
  wrap.append(table);
  return wrap;
}

function analyticsFilterSummary(data, filters) {
  const parts = [];
  for (const [key, items, label] of [
    ["class_id", data.available_classes || [], "name"],
    ["teacher_id", data.teachers || [], "first_name"],
    ["block", data.available_blocks || [], "name"]
  ]) {
    if (filters[key]) parts.push(items.find(item => String(item.id) === String(filters[key]))?.[label] || filters[key]);
  }
  if (filters.from_date || filters.to_date) {
    parts.push(filters.from_date && filters.to_date
      ? `${analyticsDate(filters.from_date)} — ${analyticsDate(filters.to_date)}`
      : filters.from_date ? `С ${analyticsDate(filters.from_date)}` : `До ${analyticsDate(filters.to_date)}`);
  }
  if (filters.q) parts.push(`Тема: ${filters.q}`);
  return parts;
}

function analyticsFilters(data, filters) {
  const drawer = node("details", undefined, "analytics-filter-drawer");
  const summary = node("summary"), title = node("span", "Фильтры", "analytics-filter-title");
  title.prepend(studioIcon("M4 6h16M7 12h10M10 18h4"));
  const active = analyticsFilterSummary(data, filters);
  summary.append(title, node("span", active.length ? `${active.length} выбрано` : "Все классы · весь период", "analytics-filter-hint"));
  drawer.append(summary);
  const form = node("form", undefined, "analytics-filter-form"), controls = {};
  function selectField(key, title, empty, items, labelKey) {
    const label = node("label", title), select = node("select");
    select.name = key;
    select.append(new Option(empty, ""));
    items.forEach(item => select.append(new Option(item[labelKey], item.id)));
    select.value = filters[key] || "";
    label.append(select);
    controls[key] = select;
    form.append(label);
  }
  selectField("class_id", "Класс", "Все классы", data.available_classes || [], "name");
  if (data.scope === "school") selectField("teacher_id", "Учитель", "Все учителя", data.teachers || [], "first_name");
  selectField("block", "Раздел предмета", "Все разделы", data.available_blocks || [], "name");
  const dates = node("fieldset", undefined, "analytics-date-range");
  dates.append(node("legend", "Период проведения"));
  const dateInputs = node("div", undefined, "analytics-date-fields");
  for (const [key, title] of [["from_date", "С даты"], ["to_date", "По дату"]]) {
    const label = node("label", title), input = node("input");
    input.type = "date";
    input.name = key;
    input.value = filters[key] || "";
    label.append(input);
    dateInputs.append(label);
    controls[key] = input;
  }
  dates.append(dateInputs);
  form.append(dates);
  const topicLabel = node("label", "Тема или название работы", "analytics-filter-topic"), topicInput = node("input");
  topicInput.type = "search";
  topicInput.name = "q";
  topicInput.maxLength = 160;
  topicInput.placeholder = "Например, квадратные уравнения";
  topicInput.value = filters.q || "";
  topicLabel.append(topicInput);
  controls.q = topicInput;
  form.append(topicLabel);
  const footer = node("div", undefined, "analytics-filter-footer"), apply = node("button", "Применить", "button primary");
  apply.type = "submit";
  footer.append(apply, classButton("Сбросить", () => busy("Обновляем статистику", () => openAnalytics({scope: data.scope})), "secondary"));
  form.append(footer);
  function validateDates() {
    controls.to_date.setCustomValidity(controls.from_date.value && controls.to_date.value && controls.from_date.value > controls.to_date.value
      ? "Дата окончания должна быть не раньше даты начала." : "");
  }
  controls.from_date.addEventListener("input", validateDates);
  controls.to_date.addEventListener("input", validateDates);
  form.addEventListener("submit", event => {
    event.preventDefault();
    validateDates();
    if (!form.reportValidity()) return;
    const nextFilters = {scope: data.scope};
    for (const [key, input] of Object.entries(controls)) if (input.value.trim()) nextFilters[key] = input.value.trim();
    busy("Считаем результаты", () => openAnalytics(nextFilters));
  });
  drawer.append(form);
  const container = node("div", undefined, "analytics-filter-area");
  container.append(drawer);
  if (active.length) {
    const selection = node("div", undefined, "analytics-active-filters");
    selection.setAttribute("aria-label", "Выбранные фильтры");
    active.forEach(text => selection.append(node("span", text, "analytics-filter-chip")));
    selection.append(classButton("Сбросить всё", () => busy("Обновляем статистику", () => openAnalytics({scope: data.scope})), "ghost"));
    container.append(selection);
  }
  return container;
}

function analyticsTopicEditor(work, data) {
  const topic = node("div", undefined, "analytics-work-topic");
  topic.append(node("strong", work.topic));
  if (work.title && work.title !== work.topic) topic.append(node("small", work.title));
  if (data.scope === "school") {
    topic.append(node("small", work.teacher));
    return topic;
  }
  const editor = node("details", undefined, "analytics-topic-edit"), summary = node("summary", "Изменить тему");
  const form = node("form"), label = node("label", "Тема работы"), input = node("input");
  input.value = work.topic;
  input.maxLength = 160;
  input.required = true;
  input.setAttribute("aria-label", "Тема: " + work.title);
  label.append(input);
  const save = node("button", "Сохранить", "button secondary");
  save.type = "submit";
  form.append(label, save);
  form.addEventListener("submit", event => {
    event.preventDefault();
    busy("Сохраняем тему", async () => {
      await request(`/api/v2/assignments/${work.id}/topic`, classJson("PUT", {topic: input.value, revision: work.revision}));
      await openAnalytics(data.filters);
    });
  });
  editor.append(summary, form);
  topic.append(editor);
  return topic;
}

async function openAnalytics(filters = {scope: "teacher"}) {
  if (!state.auth?.authenticated) { notice("Сначала войдите через MAX.", true); return; }
  const data = (await request("/api/v2/analytics?" + new URLSearchParams(filters))).report;
  analyticsState.report = data;
  analyticsState.insight = null;
  showView("analytics", false);
  const view = $("analyticsView"), heading = batchHeading(data.scope === "school" ? "Статистика школы" : "Статистика классов", data.scope === "school" ? data.title : undefined);
  view.replaceChildren(heading);
  const summary = node("section", undefined, "analytics-overview");
  summary.setAttribute("aria-label", "Сводные результаты");
  const totals = data.totals, kpis = node("div", undefined, "metrics-grid");
  kpis.append(
    analyticStat("Выполнение заданий", percentage(totals.percent), "По подтверждённым результатам", "metric-card-featured"),
    analyticStat("Проверено работ", `${totals.confirmed} / ${totals.expected}`, `${percentage(totals.coverage)} от назначенных`),
    analyticStat("Ожидают проверки", totals.needs_review, "Включая исправления учеников", totals.needs_review ? "metric-card-attention" : ""),
    analyticStat("Классов в отчёте", totals.classes, `Тем: ${data.topics.length} · заданных работ: ${totals.assignments}`)
  );
  summary.append(kpis);
  const actions = node("div", undefined, "analytics-actions");
  const pdf = classButton("Отчёт PDF", () => busy("Готовим отчёт", () => enqueueJob("analytics_pdf", {filters: data.filters, insight_id: analyticsState.insight?.insight_id})), "primary");
  const ai = classButton("Рекомендации", () => busy("Готовим рекомендации", () => enqueueJob("analytics_insight", {filters: data.filters})), "secondary analytics-recommendations");
  pdf.prepend(studioIcon("M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h5"));
  ai.prepend(studioIcon("M12 3a7 7 0 0 0-4 12.7V18h8v-2.3A7 7 0 0 0 12 3zM9 22h6"));
  pdf.disabled = ai.disabled = !totals.confirmed;
  if (!totals.confirmed) pdf.title = ai.title = "Доступно после подтверждения первой работы";
  const csv = node("a", "Таблица CSV", "button secondary");
  csv.href = "/api/v2/analytics.csv?" + new URLSearchParams(data.filters);
  csv.download = "ЛистОК статистика.csv";
  actions.append(pdf, csv, ai);
  summary.append(actions);
  if (!totals.confirmed && data.works.length) summary.append(node("p", "Подтвердите результаты проверки, чтобы получить отчёт и рекомендации.", "analytics-helper"));
  view.append(summary, analyticsFilters(data, filters));
  const insight = node("section", undefined, "panel insight-panel");
  insight.id = "analyticsInsight";
  insight.hidden = true;
  view.append(insight);
  if (!data.works.length) {
    const empty = node("section", undefined, "analytics-empty");
    const filtered = analyticsFilterSummary(data, filters).length > 0;
    empty.append(studioIcon("M4 20V10h4v10M10 20V4h4v16M16 20v-8h4v8"), node("h2", filtered ? "Нет работ по этим условиям" : "Результаты появятся здесь"), node("p", filtered ? "Измените период, класс или тему." : "Назначенные работы и подтверждённые результаты составят статистику классов."));
    if (filtered) empty.append(classButton("Показать все работы", () => busy("Обновляем статистику", () => openAnalytics({scope: data.scope})), "secondary"));
    view.append(empty);
    return;
  }
  const grid = node("div", undefined, "analytics-grid"), classes = node("section", undefined, "panel analytics-breakdown"), topics = node("section", undefined, "panel analytics-breakdown");
  classes.append(node("h2", "По классам"));
  topics.append(node("h2", "По темам"), node("p", "Сначала темы с меньшим выполнением", "analytics-helper"));
  for (const item of data.classes) {
    const row = node("div", undefined, "progress-row"), top = node("div"), bar = node("div", undefined, "progress-track");
    const fill = node("span", undefined, analyticsTone(item.percent));
    fill.style.width = Math.max(0, Math.min(100, item.percent ?? 0)) + "%";
    bar.setAttribute("aria-hidden", "true");
    bar.append(fill);
    top.append(node("strong", item.name), node("span", percentage(item.percent), "score-chip " + analyticsTone(item.percent)));
    row.append(top, bar, node("small", `Проверено ${item.confirmed} из ${item.expected}`));
    classes.append(row);
  }
  if (!data.classes.length) classes.append(node("p", "В выбранных работах ещё нет учеников.", "analytics-helper"));
  for (const item of [...data.topics].sort((a, b) => (a.percent ?? 101) - (b.percent ?? 101))) {
    const row = node("div", undefined, "topic-row"), text = node("div");
    text.append(node("strong", item.topic), node("small", `${subjectLabel(item.subject)} · проверено ${item.confirmed}`));
    row.append(text, node("span", percentage(item.percent), "score-chip " + analyticsTone(item.percent)));
    topics.append(row);
  }
  if (!data.topics.length) topics.append(node("p", "Темы появятся после добавления учеников в работы.", "analytics-helper"));
  grid.append(classes, topics);
  view.append(grid);
  if (data.blocks?.length) {
    const section = node("details", undefined, "panel analytics-blocks"), title = node("summary", "По разделам предметов");
    section.append(title);
    for (const item of data.blocks) {
      const row = node("div", undefined, "topic-row"), label = node("div");
      label.append(node("strong", item.name), node("small", `Проверено ${item.confirmed} из ${item.expected}`));
      row.append(label, node("span", percentage(item.percent), "score-chip " + analyticsTone(item.percent)));
      section.append(row);
    }
    view.append(section);
  }
  const workHeading = node("div", undefined, "analytics-section-heading");
  workHeading.append(node("h2", "Все работы"), node("span", String(data.works.length), "analytics-count"));
  view.append(workHeading);
  const rows = data.works.map(work => [
    node("strong", work.class_name), analyticsTopicEditor(work, data), analyticsDate(work.date),
    `${work.confirmed} из ${work.expected}`,
    node("span", percentage(work.percent), "score-chip " + analyticsTone(work.percent))
  ]);
  const note = node("details", undefined, "analytics-method-note");
  note.append(node("summary", "Как считаются результаты"), node("p", "Выполнение — доля полученных баллов в подтверждённых работах. Пропуски и неподтверждённые ответы не считаются нулём. Сводный процент объединяет разные задания и не является рейтингом учеников или учителей."));
  view.append(analyticsTable(["Класс", "Тема и работа", "Дата", "Проверено", "Выполнение"], rows, "Результаты назначенных работ"), note);
}

function showAnalyticsInsight(result) {
  analyticsState.insight = result;
  const box = $("analyticsInsight");
  if (!box) return;
  box.hidden = false;
  box.replaceChildren(node("h2", "Следующий шаг"));
  const columns = node("div", undefined, "analytics-insight-columns");
  for (const [key, title] of [["observations", "Что видно по результатам"], ["actions", "Что можно сделать"]]) {
    const section = node("section"), list = node("ul");
    section.append(node("h3", title));
    for (const text of result.insight[key] || []) list.append(node("li", text));
    section.append(list);
    columns.append(section);
  }
  box.append(columns, node("p", "Рекомендации ИИ по текущему отчёту. Решение принимает учитель.", "analytics-helper"));
}

function showAnalyticsDownload(result) {
  const actions = $("analyticsView").querySelector(".analytics-actions");
  if (!actions) return;
  const link = node("a", "Скачать готовый PDF", "button primary analytics-ready-download");
  link.href = result.pdf_url;
  link.target = "_blank";
  link.rel = "noopener";
  bindArtifactDownload(link, result.artifact_id, "pdf_url", "ЛистОК статистика.pdf");
  actions.querySelector(".analytics-ready-download")?.remove();
  actions.prepend(link);
}

async function openSchool() {
  if (!state.auth?.authenticated) { notice("Сначала войдите через MAX.", true); return; }
  const school = (await request("/api/v2/school")).school;
  showView("school", false);
  const view = $("schoolView");
  view.replaceChildren(batchHeading(school?.name || "Моя школа"));
  if (!school) {
    const grid = node("div", undefined, "school-setup");
    const create = node("form", undefined, "panel school-form"), name = node("input");
    name.required = true;
    name.maxLength = 120;
    name.placeholder = "Например, школа № 12";
    name.id = "schoolName";
    const label = node("label", "Название школы");
    label.append(name);
    const button = node("button", "Создать школу", "button primary");
    button.type = "submit";
    create.append(node("h2", "Подключить школу"), node("p", "Пригласите учителей и смотрите общие результаты по классам и темам.", "analytics-helper"), label, button);
    create.addEventListener("submit", event => {
      event.preventDefault();
      busy("Создаём школу", async () => { await request("/api/v2/school", classJson("POST", {name: name.value})); await openSchool(); });
    });
    const join = node("form", undefined, "panel school-form"), code = node("input");
    code.required = true;
    code.maxLength = 80;
    code.autocomplete = "off";
    code.spellcheck = false;
    code.placeholder = "Вставьте код приглашения";
    code.id = "schoolInvite";
    const codeLabel = node("label", "Код от завуча");
    codeLabel.append(code);
    const accept = node("label", undefined, "review-check"), check = node("input");
    check.type = "checkbox";
    check.required = true;
    accept.append(check, node("span", "Разрешить завучу просмотр статистики моих классов, включая новые работы. Доступ можно отозвать, выйдя из школы."));
    const joinButton = node("button", "Присоединиться", "button primary");
    joinButton.type = "submit";
    join.append(node("h2", "Войти по приглашению"), node("p", "Завуч получит сводную статистику. Листы, сканы и ответы останутся в вашем кабинете.", "analytics-helper"), codeLabel, accept, joinButton);
    join.addEventListener("submit", event => {
      event.preventDefault();
      busy("Подключаем школу", async () => { await request("/api/v2/school/join", classJson("POST", {code: code.value, share_statistics: check.checked})); await openSchool(); });
    });
    const roles = node("div", undefined, "school-role-tabs");
    roles.setAttribute("role", "tablist");
    roles.setAttribute("aria-label", "Роль в школе");
    const forms = [create, join], tabs = [];
    function selectRole(index, focus = false) {
      forms.forEach((form, i) => {
        form.hidden = i !== index;
        tabs[i].setAttribute("aria-selected", String(i === index));
        tabs[i].tabIndex = i === index ? 0 : -1;
      });
      if (focus) tabs[index].focus();
    }
    ["Завуч / координатор", "Учитель"].forEach((text, i) => {
      const tab = node("button", text);
      tab.type = "button";
      tab.id = "schoolRole" + i;
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-controls", "schoolRolePanel" + i);
      forms[i].id = "schoolRolePanel" + i;
      forms[i].setAttribute("role", "tabpanel");
      forms[i].setAttribute("aria-labelledby", tab.id);
      tab.addEventListener("click", () => selectRole(i));
      tab.addEventListener("keydown", event => {
        if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
          event.preventDefault();
          selectRole(event.key === "Home" ? 0 : event.key === "End" ? 1 : 1 - i, true);
        }
      });
      tabs.push(tab);
      roles.append(tab);
    });
    selectRole(0);
    grid.append(roles, create, join);
    view.append(grid);
    return;
  }
  const card = node("section", undefined, "panel school-dashboard"), actions = node("div", undefined, "school-dashboard-actions");
  view.append(card);
  if (school.role === "admin") {
    card.append(node("span", "Кабинет завуча", "school-role-badge"), node("h2", "Результаты школы"), node("p", "Классы, темы и отчёты присоединившихся учителей.", "analytics-helper"));
    const inviteBox = node("div", undefined, "invite-box");
    actions.append(classButton("Статистика школы", () => busy("Собираем статистику школы", () => openAnalytics({scope: "school"})), "primary"));
    actions.append(classButton("Пригласить учителя", () => busy("Создаём приглашение", async () => {
      const result = await request("/api/v2/school/invites", {method: "POST"}), input = node("input");
      input.readOnly = true;
      input.value = result.code;
      input.setAttribute("aria-label", "Одноразовый код приглашения");
      const codeRow = node("div", undefined, "school-invite-code");
      const copy = classButton("Скопировать", async () => {
        try {
          await navigator.clipboard.writeText(result.code);
          copy.textContent = "Скопировано";
          notice("Код приглашения скопирован.");
        } catch (_) {
          input.focus();
          input.select();
          notice("Код выделен. Скопируйте его через меню устройства.");
        }
      }, "secondary");
      codeRow.append(input, copy);
      inviteBox.replaceChildren(node("strong", "Приглашение готово"), node("p", "Для одного учителя · действует 7 дней", "analytics-helper"), codeRow);
    }), "secondary"));
    card.append(actions, inviteBox);
    const teamHeading = node("div", undefined, "analytics-section-heading");
    teamHeading.append(node("h2", "Команда школы"), node("span", String(school.members.length), "analytics-count"));
    view.append(teamHeading, analyticsTable(["Участник", "Роль", "Доступ"], school.members.map(member => [
      node("strong", member.first_name), member.role === "admin" ? "Завуч / координатор" : "Учитель",
      member.role === "admin" ? node("span", "Управление", "school-role-badge") : classButton("Отозвать доступ", () => {
        if (window.confirm("Отключить учителя от школы? Его личные материалы сохранятся.")) busy("Обновляем доступ", async () => {
          await request("/api/v2/school/members/" + encodeURIComponent(member.user_id), {method: "DELETE"});
          await openSchool();
        });
      }, "ghost school-revoke")
    ]), "Участники школы и их доступ"));
    view.append(node("p", "Завучу доступны сводные результаты. Сканы и тексты ответов хранятся в кабинетах учителей.", "analytics-helper"));
  } else {
    card.append(node("span", "Кабинет учителя", "school-role-badge"), node("h2", "Вы в команде школы"), node("p", "Завуч видит сводные результаты ваших классов. Листы, сканы и ответы доступны вам.", "analytics-helper"));
    actions.append(classButton("Моя статистика", () => busy("Открываем статистику", () => openAnalytics()), "primary"), classButton("Выйти из школы", () => {
      if (window.confirm("Завуч потеряет доступ к новым отчётам ваших классов. Личные материалы сохранятся. Выйти?")) busy("Выходим из школы", async () => {
        await request("/api/v2/school/leave", {method: "POST"});
        await openSchool();
      });
    }, "ghost school-revoke"));
    card.append(actions);
  }
}

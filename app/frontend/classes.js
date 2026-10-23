"use strict";
const classState = {
  list: [],
  current: null,
  tab: "students",
  assignment: null,
  editions: [],
  recipientClass: null,
  attempt: null,
  origin: "classes",
};
const classJson = (method, body) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

function classButton(text, action, kind = "secondary") {
  const button = node("button", text, "button " + kind);
  button.type = "button";
  button.addEventListener("click", action);
  return button;
}
function classScreen(id) {
  if (
    typeof guardReviewNavigation === "function" &&
    !guardReviewNavigation(() => classScreen(id))
  )
    return false;
  if (id !== "reviewView" && typeof resetReviewEditor === "function")
    resetReviewEditor();
  for (const name of [
    "classesHome",
    "classDetail",
    "assignmentView",
    "assignmentCreate",
    "reviewView",
    "classReport",
  ])
    $(name).hidden = name !== id;
  showView("classes", false);
  window.scrollTo({ top: 0 });
  return true;
}
function classFocus(container) {
  const heading = container.querySelector("h1");
  if (heading) {
    heading.tabIndex = -1;
    heading.focus({ preventScroll: true });
  }
}
async function refreshClasses() {
  classState.list = (await request("/api/v2/classes")).classes;
  classState.current = null;
  classState.assignment = null;
  classScreen("classesHome");
  renderClasses();
  classFocus($("classesHome"));
}
function renderClasses() {
  const target = $("classesList");
  target.replaceChildren();
  const archived = $("classArchiveFilter").value === "archived";
  for (const c of classState.list.filter((c) => c.archived === archived)) {
    const card = node("article", undefined, "saved-card class-card");
    card.append(
      node("h2", c.name),
      node(
        "p",
        `Учеников: ${c.student_count} · Активных работ: ${c.assignment_count}`,
        "quiet",
      ),
    );
    const actions = node("div", undefined, "actions");
    actions.append(
      classButton("Открыть класс", () =>
        busy("Открываем класс", () => openClass(c.id)),
      ),
    );
    if (!archived && c.student_count)
      actions.append(
        classButton(
          "Назначить лист",
          () => busy("Выбираем лист", () => openAssignmentForm(c.id)),
          "ghost",
        ),
      );
    card.append(actions);
    target.append(card);
  }
  if (!target.children.length)
    target.append(
      node(
        "p",
        archived
          ? "В архиве пока нет классов."
          : "Создайте первый класс, добавьте учеников и назначьте готовый лист.",
        "empty-state",
      ),
    );
}
async function openClass(id, tab = classState.tab) {
  classState.current = (await request("/api/v2/classes/" + id)).classroom;
  if (tab === "reports") await loadClassOverview(id);
  classState.tab = tab;
  classState.assignment = null;
  classScreen("classDetail");
  renderClass();
  if (tab === "reports") focusClassOverview(true);
  else classFocus($("classDetail"));
}
function renderClass() {
  const c = classState.current,
    target = $("classDetail");
  target.replaceChildren(
    classButton(
      "← Все классы",
      () => busy("Загружаем классы", refreshClasses),
      "ghost back-link",
    ),
  );
  const heading = node("div", undefined, "class-heading");
  const text = node("div");
  text.append(
    node("p", c.archived ? "КЛАСС В АРХИВЕ" : "МОЙ КЛАСС", "eyebrow"),
    node("h1", c.name),
    node(
      "p",
      `Учеников: ${c.student_count} · Активных работ: ${c.assignment_count}`,
      "quiet",
    ),
  );
  heading.append(text);
  if (!c.archived && c.student_count)
    heading.append(
      classButton(
        "Назначить лист",
        () => busy("Выбираем лист", () => openAssignmentForm(c.id)),
        "primary",
      ),
    );
  target.append(heading);
  const settings = node("details", undefined, "panel class-settings");
  settings.append(node("summary", "Настройки класса"));
  const form = node("form"),
    label = node("label", "Название класса"),
    name = node("input");
  name.value = c.name;
  name.maxLength = 60;
  name.required = true;
  label.append(name);
  const save = node("button", "Сохранить название", "button secondary");
  save.type = "submit";
  const actions = node("div", undefined, "actions");
  actions.append(save);
  const update = (archived) =>
    busy("Сохраняем класс", async () => {
      classState.current = (
        await request(
          "/api/v2/classes/" + c.id,
          classJson("PUT", {
            name: name.value,
            archived,
            revision: c.revision,
          }),
        )
      ).classroom;
      renderClass();
      notice(
        archived
          ? "Класс в архиве. Ученики и назначенные работы сохранены."
          : "Класс сохранён.",
      );
    });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    update(c.archived);
  });
  actions.append(
    classButton(
      c.archived ? "Вернуть из архива" : "В архив",
      () => update(!c.archived),
      "ghost",
    ),
  );
  form.append(
    label,
    actions,
    node(
      "p",
      "Архив сохраняет историю. Чтобы назначать новые работы, верните класс в работу.",
      "quiet",
    ),
  );
  settings.append(form);
  target.append(settings);
  const tabs = node("div", undefined, "class-tabs");
  tabs.setAttribute("aria-label", "Раздел класса");
  for (const [key, title] of [
    ["students", "Ученики"],
    ["assignments", "Работы"],
    ["reports", "Отчёты"],
  ]) {
    const button = classButton(
      title,
      () => {
        if (key === "reports") {
          busy("Загружаем отчёты класса", async () => {
            await loadClassOverview(c.id);
            classState.tab = key;
            renderClass();
            focusClassOverview();
          });
          return;
        }
        classState.tab = key;
        renderClass();
      },
      classState.tab === key ? "primary" : "secondary",
    );
    button.setAttribute("aria-pressed", String(classState.tab === key));
    tabs.append(button);
  }
  tabs.append(
    classButton(
      "Обновить",
      () => busy("Обновляем класс", () => openClass(c.id)),
      "ghost",
    ),
  );
  target.append(tabs);
  if (classState.tab === "students") renderRoster(target, c);
  else if (classState.tab === "reports") renderClassOverview(target, c);
  else renderAssignments(target, c);
}
function renderRoster(target, c) {
  const info = node("div", undefined, "panel roster-privacy");
  info.append(
    node("h2", "Ученики под кодами"),
    node(
      "p",
      "Сервис хранит только постоянные коды. Скачайте таблицу, впишите ФИО у себя на устройстве и сохраните её. Загружать заполненную таблицу сюда не нужно.",
      "quiet",
    ),
  );
  if (c.students.length)
    info.append(classButton("Скачать таблицу кодов", () => downloadCodes(c)));
  target.append(info);
  if (!c.archived) {
    const form = node("form", undefined, "panel roster-add");
    const label = node("label", "Сколько учеников добавить"),
      input = node("input");
    input.type = "number";
    input.min = "1";
    input.max = "100";
    input.value = c.students.length ? "1" : "25";
    input.required = true;
    label.append(input);
    const submit = node("button", "Создать коды учеников", "button primary");
    submit.type = "submit";
    form.append(label, submit);
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      busy("Создаём коды", async () => {
        classState.current = (
          await request(
            `/api/v2/classes/${c.id}/students`,
            classJson("POST", {
              revision: c.revision,
              count: Number(input.value),
            }),
          )
        ).classroom;
        renderClass();
        notice(
          "Коды созданы. Скачайте таблицу и заполните соответствие на своём устройстве.",
        );
      });
    });
    if (c.students.length) {
      const more = node("details", undefined, "panel");
      more.append(node("summary", "Добавить учеников"), form);
      target.append(more);
    } else target.append(form);
  }
  if (!c.students.length) return;
  const panel = node("div", undefined, "panel roster-panel"),
    label = node("label", "Найти по коду"),
    search = node("input");
  search.type = "search";
  search.placeholder = "Например, У-3A…";
  label.append(search);
  panel.append(label);
  const list = node("div", undefined, "roster-list"),
    archive = node("details", undefined, "roster-archive"),
    archivedList = node("div", undefined, "roster-list");
  archive.append(
    node("summary", `В архиве: ${c.students.filter((s) => s.archived).length}`),
    archivedList,
  );
  const draw = () => {
    list.replaceChildren();
    archivedList.replaceChildren();
    for (const s of c.students.filter((s) =>
      s.code
        .toLocaleLowerCase("ru")
        .includes(search.value.trim().toLocaleLowerCase("ru")),
    )) {
      const row = node("div", undefined, "student-row");
      row.append(node("span", s.code, "student-name"));
      if (!c.archived)
        row.append(
          classButton(
            s.archived ? "Вернуть" : "В архив",
            () =>
              busy("Обновляем список", async () => {
                classState.current = (
                  await request(
                    `/api/v2/classes/${c.id}/students/${s.id}`,
                    classJson("PUT", {
                      revision: c.revision,
                      archived: !s.archived,
                    }),
                  )
                ).classroom;
                renderClass();
                notice(
                  "Код сохранён. Состав ранее назначенных работ не изменился.",
                );
              }),
            "ghost",
          ),
        );
      (s.archived ? archivedList : list).append(row);
    }
    if (!list.children.length)
      list.append(
        node("p", "Подходящих учеников в текущем списке нет.", "quiet"),
      );
  };
  search.addEventListener("input", draw);
  draw();
  panel.append(list, archive);
  target.append(panel);
}
function downloadCodes(c) {
  const rows = [
    ["Код ученика", "ФИО — заполните только у себя", "Состояние"],
    ...c.students.map((s) => [s.code, "", s.archived ? "Архив" : "В классе"]),
  ];
  const csv =
    "\uFEFF" +
    rows
      .map((row) =>
        row.map((cell) => '"' + cell.replaceAll('"', '""') + '"').join(";"),
      )
      .join("\r\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" }),
    url = URL.createObjectURL(blob),
    link = node("a");
  link.href = url;
  link.download =
    "Коды учеников — " + c.name.replace(/[<>:\"/\\|?*]/g, "_") + ".csv";
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
  notice(
    "В таблице только коды. Заполните ФИО на своём устройстве и храните таблицу у себя.",
  );
}
function assignmentDate(value) {
  return value ? value.split("-").reverse().join(".") : "Без срока";
}
function renderAssignments(target, c) {
  const list = node("div", undefined, "saved-list assignment-list");
  for (const a of c.assignments) {
    const card = node("article", undefined, "saved-card");
    card.append(
      node(
        "span",
        a.status === "closed" ? "Закрыта" : "Назначена",
        "assignment-status",
      ),
      node("h2", a.title),
      node(
        "p",
        `${a.due_date ? "Сдать до " : ""}${assignmentDate(a.due_date)} · Учеников: ${a.student_count}`,
        "quiet",
      ),
      node(
        "p",
        (a.scheduled_date
          ? "Проведение: " + assignmentDate(a.scheduled_date) + " · "
          : "") +
          "Версия " +
          a.code,
        "quiet",
      ),
      classButton("Открыть работу", () =>
        busy("Открываем работу", () => openAssignment(a.id)),
      ),
    );
    list.append(card);
  }
  if (!c.assignments.length)
    list.append(
      node(
        "p",
        c.student_count
          ? "Назначьте сохранённый лист — он появится здесь вместе со сроком и списком учеников."
          : "Сначала добавьте учеников, затем назначьте сохранённый лист.",
        "empty-state",
      ),
    );
  target.append(list);
}
function editionDownload(editionId, code, links, key, title) {
  const a = node("a", title, "button secondary");
  a.href = links[key];
  a.target = "_blank";
  a.rel = "noopener";
  a.addEventListener("click", (e) => {
    if (!window.WebApp?.downloadFile) return;
    e.preventDefault();
    busy("Готовим файл", async () => {
      const result = await request("/api/v2/exports/" + editionId, {
        method: "POST",
      });
      await window.WebApp.downloadFile(
        new URL(result[key], location.origin).href,
        title + " " + code + ".pdf",
      );
    });
  });
  return a;
}
async function openAssignment(id, loaded = null) {
  const a = loaded || (await request("/api/v2/assignments/" + id)).assignment;
  classState.assignment = a;
  classScreen("assignmentView");
  const target = $("assignmentView");
  target.replaceChildren(
    classButton(
      "← К работам класса",
      () => busy("Открываем класс", () => openClass(a.class_id, "assignments")),
      "ghost back-link",
    ),
  );
  const panel = node("article", undefined, "panel assignment-detail");
  panel.append(
    node(
      "p",
      `${a.class_name} · ${a.status === "active" ? "НАЗНАЧЕНА" : "ЗАКРЫТА"}`,
      "eyebrow",
    ),
    node("h1", a.title),
    node(
      "p",
      `${a.due_date ? "Сдать до " : ""}${assignmentDate(a.due_date)} · Учеников: ${a.student_count}`,
      "assignment-meta",
    ),
  );
  if (a.scheduled_date)
    panel.append(
      node(
        "p",
        "Проведение: " + assignmentDate(a.scheduled_date),
        "assignment-meta",
      ),
    );
  if (a.instructions)
    panel.append(node("p", a.instructions, "assignment-instructions"));
  panel.append(
    node(
      "p",
      "Версия " + a.code + " · " + taskCount(a.worksheet.tasks.length),
      "quiet",
    ),
  );
  const downloads = node("div", undefined, "actions");
  downloads.append(
    editionDownload(
      a.edition_id,
      a.code,
      a.result,
      "pdf_url",
      "Лист для печати",
    ),
  );
  if (a.result.keys_url)
    downloads.append(
      editionDownload(
        a.edition_id,
        a.code,
        a.result,
        "keys_url",
        "Ответы для учителя",
      ),
    );
  panel.append(
    downloads,
    node(
      "p",
      "Лист и состав класса зафиксированы. Правки в материалах и списке учеников не изменяют эту работу.",
      "quiet",
    ),
  );
  panel.append(
    classButton(
      "Проверить ответы и открыть отчёт",
      () => busy("Открываем проверку", () => openClassReport(a.id)),
      "primary",
    ),
    node(
      "p",
      "Добавляйте фото ответов по коду ученика. Итоговые баллы появляются в отчёте после вашего подтверждения.",
      "quiet",
    ),
  );
  const members = node("details", undefined, "assignment-members");
  members.append(node("summary", "Кому назначено · " + a.student_count));
  const list = node("ol");
  for (const s of a.students) list.append(node("li", s.code));
  members.append(list);
  panel.append(members);
  const tasks = node("details", undefined, "assignment-tasks");
  tasks.append(node("summary", "Посмотреть задания и ответы"));
  for (const [i, t] of a.worksheet.tasks.entries()) {
    const row = node("div", undefined, "assignment-task");
    row.append(node("strong", "Задание " + (i + 1)));
    const question = node("p"),
      answer = node("p", undefined, "quiet");
    mathPreview(question, t.question);
    mathPreview(answer, "Ответ: " + t.answer);
    row.append(question, answer);
    tasks.append(row);
  }
  panel.append(tasks);
  const close = classButton(
    a.status === "active" ? "Закрыть назначение" : "Открыть назначение снова",
    () =>
      busy("Обновляем работу", async () => {
        await request(
          "/api/v2/assignments/" + a.id,
          classJson("PUT", {
            status: a.status === "active" ? "closed" : "active",
            revision: a.revision,
          }),
        );
        await openAssignment(a.id);
        notice("Статус обновлён. Лист и состав сохранены.");
      }),
    "ghost",
  );
  panel.append(close);
  target.append(panel);
  classFocus(target);
}
async function openAssignmentForm(
  classId = null,
  materialId = null,
  editionId = null,
) {
  if (classState.attempt) {
    classScreen("assignmentCreate");
    notice(
      "Сначала повторите предыдущее назначение, чтобы подтвердить его результат.",
    );
    return;
  }
  classState.origin = classId ? "classes" : "saved";
  classState.list = (await request("/api/v2/classes")).classes;
  const active = classState.list.filter((c) => !c.archived);
  if (!active.length) {
    await refreshClasses();
    notice(
      "Сначала создайте класс и добавьте учеников. Затем сможете назначить лист.",
    );
    $("newClassName").focus();
    return;
  }
  const materials = (await request("/api/v2/materials")).materials.filter(
    (m) => m.edition_count > 0,
  );
  if (!materials.length) {
    showView("saved", false);
    await refreshMaterials();
    notice(
      "Для назначения нужен готовый PDF. Откройте или создайте лист, проверьте ответы и соберите его.",
    );
    return;
  }
  $("assignmentForm").reset();
  $("assignmentFields").disabled = false;
  $("assignmentRetryHint").hidden = true;
  $("assignSubmit").textContent = "Назначить работу";
  classState.attempt = null;
  $("assignClass").replaceChildren();
  for (const c of active) {
    const option = node("option", c.name + " · учеников: " + c.student_count);
    option.value = c.id;
    $("assignClass").append(option);
  }
  if (active.some((c) => c.id === classId)) $("assignClass").value = classId;
  $("assignMaterial").replaceChildren();
  for (const m of materials) {
    const option = node(
      "option",
      m.worksheet.title + (m.archived ? " · архив" : ""),
    );
    option.value = m.id;
    $("assignMaterial").append(option);
  }
  if (materials.some((m) => m.id === materialId))
    $("assignMaterial").value = materialId;
  await selectRecipientClass();
  await selectAssignmentMaterial(editionId);
  classScreen("assignmentCreate");
  classFocus($("assignmentCreate"));
}
async function selectRecipientClass() {
  classState.recipientClass = null;
  $("assignSubmit").disabled = true;
  const c = (await request("/api/v2/classes/" + $("assignClass").value))
    .classroom;
  classState.recipientClass = c;
  const summary = $("assignRosterSummary");
  summary.replaceChildren(
    node(
      "span",
      c.student_count
        ? `Работа будет назначена ученикам из текущего списка: ${c.student_count}.`
        : "В классе пока нет учеников. ",
    ),
  );
  if (!c.student_count)
    summary.append(
      classButton(
        "Добавить учеников",
        () => busy("Открываем список", () => openClass(c.id, "students")),
        "ghost",
      ),
    );
  $("assignSubmit").disabled = !c.student_count || c.archived;
}
async function selectAssignmentMaterial(preferredId) {
  classState.editions = [];
  $("assignEdition").replaceChildren();
  $("assignPreview").replaceChildren();
  $("assignSubmit").disabled = true;
  classState.editions = (
    await request(
      "/api/v2/materials/" + $("assignMaterial").value + "/editions",
    )
  ).editions;
  $("assignEdition").replaceChildren();
  for (const e of classState.editions) {
    const option = node(
      "option",
      new Date(e.created).toLocaleString("ru-RU") + " · " + e.code,
    );
    option.value = e.id;
    $("assignEdition").append(option);
  }
  if (classState.editions.some((e) => e.id === preferredId))
    $("assignEdition").value = preferredId;
  renderAssignmentPreview();
}
function renderAssignmentPreview() {
  const e = classState.editions.find((e) => e.id === $("assignEdition").value);
  const preview = $("assignPreview");
  preview.replaceChildren();
  if (!e) {
    preview.append(
      node("p", "Версия больше не доступна. Выберите другой лист."),
    );
    $("assignSubmit").disabled = true;
    return;
  }
  $("assignTitle").value = e.worksheet.title;
  preview.append(
    node("strong", e.worksheet.title),
    node(
      "p",
      taskCount(e.worksheet.tasks.length) + " · Код " + e.code,
      "quiet",
    ),
  );
  const details = node("details");
  details.append(node("summary", "Проверить задания перед назначением"));
  for (const [i, t] of e.worksheet.tasks.entries()) {
    const p = node("p");
    mathPreview(p, i + 1 + ". " + t.question);
    details.append(p);
  }
  preview.append(details);
  $("assignSubmit").disabled =
    !classState.recipientClass?.student_count ||
    classState.recipientClass.archived;
}
function backFromClass() {
  if (!$("reviewView").hidden) {
    busy("Открываем отчёт", () =>
      openClassReport(reviewState.current.assignment_id),
    );
  } else if (!$("classReport").hidden) {
    const origin = reviewState.reportOrigin;
    if (origin?.assignmentId === reviewState.report.assignment_id)
      busy("Открываем обзор класса", () =>
        openClass(origin.classId, "reports"),
      );
    else
      busy("Открываем работу", () =>
        openAssignment(reviewState.report.assignment_id),
      );
  } else if (!$("assignmentCreate").hidden) {
    if (classState.attempt) {
      notice(
        "Запрос ещё не подтверждён. Нажмите «Повторить назначение», чтобы безопасно узнать результат.",
        true,
      );
      return;
    }
    if (classState.origin === "saved") {
      showView("saved");
      return;
    }
    busy("Открываем класс", () => openClass(classState.recipientClass.id));
  } else if (!$("assignmentView").hidden)
    busy("Открываем класс", () =>
      openClass(classState.assignment.class_id, "assignments"),
    );
  else if (!$("classDetail").hidden) busy("Загружаем классы", refreshClasses);
  else showView("workspace");
}
$("classesNav").addEventListener("click", () => showView("classes"));
$("classArchiveFilter").addEventListener("change", renderClasses);
$("newClassForm").addEventListener("submit", (e) => {
  e.preventDefault();
  busy("Создаём класс", async () => {
    const c = (
      await request(
        "/api/v2/classes",
        classJson("POST", { name: $("newClassName").value }),
      )
    ).classroom;
    $("newClassName").value = "";
    await openClass(c.id, "students");
    notice("Класс создан. Добавьте учеников — можно сразу списком.");
  });
});
$("assignClass").addEventListener("change", () =>
  busy("Обновляем состав класса", selectRecipientClass),
);
$("assignMaterial").addEventListener("change", () =>
  busy("Загружаем версии", selectAssignmentMaterial),
);
$("assignEdition").addEventListener("change", renderAssignmentPreview);
$("cancelAssignment").addEventListener("click", backFromClass);
$("assignmentForm").addEventListener("submit", (e) => {
  e.preventDefault();
  busy("Назначаем работу", async () => {
    if (!classState.attempt)
      classState.attempt = {
        classId: classState.recipientClass.id,
        body: {
          revision: classState.recipientClass.revision,
          edition_id: $("assignEdition").value,
          title: $("assignTitle").value,
          due_date: $("assignDue").value,
          scheduled_date: $("assignScheduled").value,
          instructions: $("assignInstructions").value,
          request_key: crypto.randomUUID(),
        },
      };
    $("assignmentFields").disabled = true;
    try {
      const a = (
        await request(
          "/api/v2/classes/" + classState.attempt.classId + "/assignments",
          classJson("POST", classState.attempt.body),
        )
      ).assignment;
      await openAssignment(a.id, a);
      classState.attempt = null;
      notice("Работа назначена и сохранена в кабинете.");
    } catch (error) {
      if (error.status && error.status < 500) {
        classState.attempt = null;
        $("assignmentFields").disabled = false;
        await selectRecipientClass();
      } else {
        $("assignmentRetryHint").hidden = false;
        $("assignSubmit").textContent = "Повторить назначение";
      }
      throw error;
    }
  });
});

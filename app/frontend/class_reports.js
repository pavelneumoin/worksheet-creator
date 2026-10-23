"use strict";
const classReportsState = { classId: null, filters: {}, data: null };

async function loadClassOverview(id, filters = null) {
  if (classReportsState.classId !== id) {
    classReportsState.classId = id;
    classReportsState.filters = {};
    classReportsState.data = null;
  }
  const query = new URLSearchParams(filters || classReportsState.filters);
  const data = (await request(`/api/v2/classes/${id}/report?${query}`)).report;
  classReportsState.filters = data.filters;
  classReportsState.data = data;
}
function focusClassOverview(results = false) {
  const heading = $(results ? "classOverviewResults" : "classOverviewHeading");
  if (heading) {
    heading.tabIndex = -1;
    // The busy overlay makes main inert until the action returns.
    setTimeout(() => {
      if (
        heading.isConnected &&
        !$("classDetail").hidden &&
        state.view === "classes"
      ) {
        heading.focus({ preventScroll: true });
        heading.scrollIntoView({ block: "start" });
      }
    }, 0);
  }
}
function renderClassOverview(target, c) {
  const data = classReportsState.data;
  if (!data || data.class_id !== c.id) return;
  const heading = node("h2", "Работы и результаты");
  heading.id = "classOverviewHeading";
  const panel = node("section", undefined, "panel class-overview-filters");
  panel.append(
    heading,
    node(
      "p",
      "Каждая работа — со своим составом и максимумом баллов. В результатах учитываются только подтверждённые проверки.",
      "quiet",
    ),
  );
  const form = node("form"),
    searchLabel = node("label", "Тема или название работы"),
    search = node("input");
  search.type = "search";
  search.maxLength = 160;
  search.value = data.filters.q;
  search.placeholder = "Например, уравнения";
  searchLabel.append(search);
  form.append(searchLabel);
  const options = node("details", undefined, "class-overview-options");
  options.open = Object.entries(data.filters).some(
    ([key, value]) => key !== "q" && value,
  );
  options.append(node("summary", "Период, предмет и код ученика"));
  const fields = node("div", undefined, "class-overview-fields");
  const inputs = { q: search };
  for (const [key, labelText] of [
    ["from_date", "Проведение с"],
    ["to_date", "Проведение по"],
  ]) {
    const label = node("label", labelText),
      input = node("input");
    input.type = "date";
    input.value = data.filters[key];
    label.append(input);
    fields.append(label);
    inputs[key] = input;
  }
  for (const [key, labelText, choices] of [
    [
      "subject",
      "Предмет",
      [
        ["", "Все предметы"],
        ["math", "Математика"],
        ["physics", "Физика"],
      ],
    ],
    [
      "status",
      "Состояние работы",
      [
        ["", "Все работы"],
        ["active", "Назначенные"],
        ["closed", "Закрытые"],
      ],
    ],
    [
      "student_id",
      "Результат ученика",
      [
        ["", "Весь класс"],
        ...data.students.map((s) => [
          s.id,
          s.code + (s.archived ? " · архив" : ""),
        ]),
      ],
    ],
  ]) {
    const label = node("label", labelText),
      select = node("select");
    for (const [value, text] of choices) {
      const option = node("option", text);
      option.value = value;
      select.append(option);
    }
    select.value = data.filters[key];
    label.append(select);
    fields.append(label);
    inputs[key] = select;
  }
  const dateHint = node(
    "p",
    "Период относится к дате проведения, а не к сроку сдачи. При выборе периода работы без даты не показываются.",
    "quiet",
  );
  options.append(fields, dateHint);
  const actions = node("div", undefined, "actions");
  const submit = node("button", "Показать отчёты", "button primary");
  submit.type = "submit";
  const apply = (filters) =>
    busy("Загружаем отчёты класса", async () => {
      await loadClassOverview(c.id, filters);
      renderClass();
      focusClassOverview(true);
    });
  actions.append(
    submit,
    classButton("Сбросить фильтры", () => apply({}), "ghost"),
  );
  const error = node("p", "", "review-warning");
  error.hidden = true;
  error.setAttribute("role", "alert");
  form.append(options, actions, error);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (
      inputs.from_date.value &&
      inputs.to_date.value &&
      inputs.from_date.value > inputs.to_date.value
    ) {
      error.hidden = false;
      error.textContent = "Начало периода не может быть позже конца.";
      error.scrollIntoView({ block: "nearest" });
      return;
    }
    apply(
      Object.fromEntries(
        Object.entries(inputs).map(([key, input]) => [key, input.value]),
      ),
    );
  });
  panel.append(form);
  target.append(panel);
  const summary = node("section", undefined, "panel class-overview-summary");
  const totals = data.totals;
  const resultsHeading = node(
    "h2",
    `Работы: ${totals.works} из ${data.available_work_count}`,
  );
  resultsHeading.id = "classOverviewResults";
  summary.append(
    resultsHeading,
    node(
      "p",
      `Подтверждено проверок: ${totals.confirmed} из ${totals.total} назначений ученикам. Ожидаются: ${totals.not_submitted}.`,
    ),
    node(
      "p",
      `Нужен учитель: ${totals.needs_review} · Распознаются: ${totals.processing} · С ошибкой: ${totals.failed} · Черновики исправлений: ${totals.pending_corrections}.`,
      "quiet",
    ),
    node(
      "p",
      "Один ученик может иметь несколько назначений. Средние баллы разных листов не объединяются: задания и сложность могут отличаться.",
      "quiet",
    ),
  );
  if (totals.undated)
    summary.append(
      node(
        "p",
        `Без даты проведения: ${totals.undated}. Они показаны после датированных работ.`,
        "quiet",
      ),
    );
  summary.append(
    node(
      "p",
      "Обновлено: " + new Date(data.generated_at).toLocaleString("ru-RU"),
      "quiet",
    ),
  );
  if (data.selected_student)
    summary.append(
      node(
        "p",
        "На карточках выбран " +
          data.selected_student.code +
          ". Сводка выше относится ко всему классу; баллы ученика показаны отдельно.",
      ),
    );
  target.append(summary);
  const list = node("div", undefined, "class-overview-list");
  for (const work of data.works) {
    const card = node("article", undefined, "panel class-overview-card"),
      s = work.summary;
    card.append(
      node(
        "p",
        (work.subject === "physics" ? "Физика" : "Математика") +
          " · " +
          (work.status === "closed" ? "Закрыта" : "Назначена"),
        "eyebrow",
      ),
      node("h3", work.title),
    );
    if (work.topic !== work.title)
      card.append(node("p", "Тема листа: " + work.topic, "quiet"));
    card.append(
      node(
        "p",
        "Проведение: " +
          (work.scheduled_date
            ? assignmentDate(work.scheduled_date)
            : "дата не указана") +
          " · " +
          (work.due_date
            ? "Сдать до " + assignmentDate(work.due_date)
            : "Без срока сдачи"),
        "quiet",
      ),
      node(
        "p",
        "Версия " + work.edition_code + " · Максимум: " + s.maximum,
        "quiet",
      ),
      node(
        "p",
        `Получено: ${s.submitted} из ${s.total} · Подтверждено: ${s.confirmed} из ${s.total} · Ожидаются: ${s.not_submitted}`,
      ),
      node(
        "p",
        s.average === null
          ? "Подтверждённых результатов пока нет."
          : `Средний балл: ${s.average.toLocaleString("ru-RU")} из ${s.maximum} · Выполнение: ${s.percent.toLocaleString("ru-RU")}%`,
        "class-overview-score",
      ),
      node(
        "p",
        `В расчёте: ${s.confirmed} из ${s.total} назначенных учеников.`,
        "quiet",
      ),
    );
    if (s.needs_review || s.failed || s.processing)
      card.append(
        node(
          "p",
          `Нужен учитель: ${s.needs_review} · С ошибкой: ${s.failed} · Распознаются: ${s.processing}`,
          "quiet",
        ),
      );
    if (s.pending_corrections)
      card.append(
        node(
          "p",
          `Исправлений в черновике: ${s.pending_corrections}. Пока учтены прежние подтверждённые баллы.`,
          "review-warning",
        ),
      );
    if (work.student_result) {
      const result = work.student_result;
      card.append(
        node(
          "p",
          data.selected_student.code +
            ": " +
            (result.status === "not_assigned"
              ? "Эта работа не назначалась"
              : reviewLabels[result.status]) +
            (result.score === null ? "" : ` · ${result.score} из ${s.maximum}`),
          "class-overview-individual",
        ),
      );
      if (result.has_draft)
        card.append(
          node("p", "У ученика есть сохранённый черновик правок.", "quiet"),
        );
    }
    const workActions = node("div", undefined, "actions");
    workActions.append(
      classButton("Отчёт и проверка", () =>
        busy("Открываем отчёт работы", async () => {
          reviewState.reportOrigin = {
            classId: c.id,
            assignmentId: work.assignment_id,
          };
          await openClassReport(work.assignment_id);
        }),
      ),
    );
    if (work.student_result?.review_id)
      workActions.append(
        classButton("Проверка ученика", () =>
          busy("Открываем проверку ученика", async () => {
            reviewState.reportOrigin = {
              classId: c.id,
              assignmentId: work.assignment_id,
            };
            await openReview(work.student_result.review_id);
          }),
        ),
      );
    card.append(workActions);
    list.append(card);
  }
  if (!data.works.length)
    list.append(
      node(
        "p",
        data.available_work_count
          ? "По этим фильтрам работ нет. Измените период или сбросьте фильтры."
          : "Пока нет назначенных работ. Добавьте учеников и назначьте сохранённый лист.",
        "empty-state",
      ),
    );
  target.append(list);
}

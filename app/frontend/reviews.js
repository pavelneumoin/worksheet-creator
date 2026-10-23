"use strict";
const reviewState = {
  current: null,
  report: null,
  files: [],
  assignmentId: null,
  pending: null,
  timer: null,
  editor: null,
  navigation: null,
};
const reviewLabels = {
  not_submitted: "Не сдал",
  processing: "Распознаётся",
  needs_review: "Нужен учитель",
  failed: "Ошибка распознавания",
  confirmed: "Подтверждено",
};

function reviewButton(text, action, cls = "secondary") {
  return classButton(text, () => busy(text, action), cls);
}
function hasUnsavedReview() {
  const e = reviewState.editor;
  return !!(e && (e.changed !== e.saved || e.saving));
}
function resetReviewEditor() {
  clearTimeout(reviewState.editor?.timer);
  reviewState.editor = null;
  syncClosingConfirmation();
}
function editReviewDraft() {
  const e = reviewState.editor;
  if (!e) return;
  e.changed++;
  e.status.textContent = "Сохраняем правки в вашем кабинете…";
  e.status.classList.remove("review-warning");
  clearTimeout(e.timer);
  e.timer = setTimeout(() => flushReviewDraft().catch(() => {}), 800);
  syncClosingConfirmation();
}
async function flushReviewDraft() {
  const e = reviewState.editor;
  if (!e) return;
  clearTimeout(e.timer);
  if (e.saving) return e.saving;
  if (e.changed === e.saved) return;
  e.saving = (async () => {
    try {
      while (e.changed !== e.saved) {
        const sequence = e.changed;
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 15000);
        let result;
        try {
          result = await request(`/api/v2/reviews/${e.id}/draft`, {
            ...classJson("PUT", {
              ...e.body(),
              draft_revision: e.draftRevision,
            }),
            signal: controller.signal,
          });
        } finally {
          clearTimeout(timeout);
        }
        e.draftRevision = result.draft.revision;
        e.saved = sequence;
      }
      e.status.textContent =
        "Правки сохранены в кабинете · " +
        new Date().toLocaleTimeString("ru-RU", {
          hour: "2-digit",
          minute: "2-digit",
        }) +
        ". Баллы попадут в отчёт после подтверждения.";
      e.status.classList.remove("review-warning");
    } catch (error) {
      const message =
        error.name === "AbortError" || error instanceof TypeError
          ? "Нет ответа от сервера. Проверьте подключение."
          : error.message;
      e.status.textContent =
        "Правки пока не сохранены. " +
        message +
        " Можно повторить сохранение или скачать свои правки ниже.";
      e.status.classList.add("review-warning");
      throw new Error(message);
    } finally {
      e.saving = null;
      syncClosingConfirmation();
    }
  })();
  syncClosingConfirmation();
  return e.saving;
}
function guardReviewNavigation(action) {
  if (!hasUnsavedReview()) return true;
  reviewState.navigation = action;
  if (!reviewState.leaving) {
    reviewState.leaving = true;
    flushReviewDraft()
      .then(() => {
        const next = reviewState.navigation;
        reviewState.navigation = null;
        next?.();
      })
      .catch((error) =>
        notice(error.message + " Правки остаются на экране.", true),
      )
      .finally(() => {
        reviewState.leaving = false;
      });
  }
  return false;
}
document.addEventListener("visibilitychange", () => {
  if (document.hidden && hasUnsavedReview()) flushReviewDraft().catch(() => {});
});
function clearReviewFiles() {
  for (const f of reviewState.files) URL.revokeObjectURL(f.url);
  reviewState.files = [];
}
async function openClassReport(id) {
  await flushReviewDraft();
  if (reviewState.pending && reviewState.pending.assignmentId !== id)
    throw new Error(
      "Сначала повторите отправку фото в предыдущей работе, чтобы узнать результат.",
    );
  const data = (await request(`/api/v2/assignments/${id}/report`)).report;
  if (reviewState.assignmentId !== id) clearReviewFiles();
  reviewState.assignmentId = id;
  reviewState.report = data;
  classScreen("classReport");
  const target = $("classReport");
  target.className = "review-report";
  const origin =
    reviewState.reportOrigin?.assignmentId === id
      ? reviewState.reportOrigin
      : null;
  target.replaceChildren(
    reviewButton(
      origin ? "← К обзору работ" : "← К назначенной работе",
      () =>
        origin ? openClass(origin.classId, "reports") : openAssignment(id),
      "ghost back-link report-controls",
    ),
  );
  const heading = node("div", undefined, "class-heading");
  const text = node("div");
  text.append(
    node("p", data.class_name + " · ОТЧЁТ ПО РАБОТЕ", "eyebrow"),
    node("h1", data.title),
    node(
      "p",
      "Версия " +
        data.edition_code +
        (data.scheduled_date
          ? " · " + assignmentDate(data.scheduled_date)
          : " · Без даты проведения") +
        (data.due_date
          ? " · Сдать до " + assignmentDate(data.due_date)
          : " · Без срока сдачи"),
      "quiet",
    ),
  );
  heading.append(text);
  text.append(
    node(
      "p",
      "Отчёт на " + new Date(data.generated_at).toLocaleString("ru-RU"),
      "quiet report-snapshot",
    ),
  );
  target.append(heading);
  const summary = node("div", undefined, "report-summary");
  for (const [label, value] of [
    ["В составе", data.summary.total],
    ["Получено", data.summary.submitted],
    ["Подтверждено", data.summary.confirmed],
    ["Нужен учитель", data.summary.needs_review],
    ["Ожидаются", data.summary.not_submitted],
  ]) {
    const card = node("div", undefined, "report-stat");
    card.append(node("strong", String(value)), node("span", label));
    summary.append(card);
  }
  target.append(summary);
  const average = node("section", undefined, "panel");
  average.append(
    node("h2", "Результаты класса"),
    node(
      "p",
      data.summary.average === null
        ? "Подтверждённых баллов пока нет."
        : `Средний балл: ${data.summary.average.toLocaleString("ru-RU")} из ${data.summary.maximum} · Выполнение: ${data.summary.percent.toLocaleString("ru-RU")}%`,
    ),
    node(
      "p",
      `В расчёте только подтверждённые работы: ${data.summary.confirmed} из ${data.summary.total}. Черновики и несданные работы исключены.`,
      "quiet",
    ),
    node("p", data.recommendation),
  );
  if (data.summary.pending_corrections)
    average.append(
      node(
        "p",
        `Черновики исправлений: ${data.summary.pending_corrections}. Для этих работ в расчёте остаются прежние подтверждённые баллы.`,
        "review-warning",
      ),
    );
  if (data.summary.processing || data.summary.failed)
    average.append(
      node(
        "p",
        `Распознаются: ${data.summary.processing} · С ошибкой: ${data.summary.failed}`,
        "quiet",
      ),
    );
  const controls = node("div", undefined, "actions report-controls");
  const csv = node("a", "Скачать CSV", "button secondary");
  csv.href = `/api/v2/assignments/${id}/report.csv`;
  csv.download = "Отчёт по классу.csv";
  controls.append(
    csv,
    reviewButton("Подготовить PDF", () =>
      enqueueJob("report_pdf", { assignment_id: id }),
    ),
    classButton("Печать отчёта", () => {
      document.body.dataset.printReport = "true";
      window.print();
    }),
    reviewButton("Обновить", () => openClassReport(id), "ghost"),
  );
  average.append(controls);
  target.append(average);
  const taskPanel = node("section", undefined, "panel");
  taskPanel.append(node("h2", "Задания для повторения"));
  for (const [i, t] of data.tasks.entries()) {
    const row = node("div", undefined, "report-task");
    const caption = node("p");
    mathPreview(caption, `${i + 1}. ${t.question}`);
    row.append(
      caption,
      node(
        "strong",
        t.percent === null
          ? "Нет данных"
          : `${t.correct} из ${t.total} · ${t.percent}%`,
      ),
    );
    taskPanel.append(row);
  }
  target.append(taskPanel);
  const roster = node("section", undefined, "panel");
  roster.append(node("h2", "Работы учеников"));
  for (const student of data.students) {
    const row = node("div", undefined, "report-student");
    const info = node("div");
    info.append(
      node("strong", student.code),
      node(
        "p",
        reviewLabels[student.status] +
          (student.score !== null
            ? ` · ${student.score} из ${student.maximum}`
            : ""),
        "quiet",
      ),
    );
    row.append(info);
    if (student.has_draft)
      info.append(node("p", "Есть сохранённые правки", "quiet"));
    if (student.review_id)
      row.append(
        reviewButton(
          student.status === "confirmed" ? "Результат" : "Открыть",
          () => openReview(student.review_id),
        ),
      );
    roster.append(row);
  }
  target.append(roster);
  renderReviewUpload(target, data);
  classFocus(target);
}
function showReportDownload(result) {
  const panel = node(
    "section",
    undefined,
    "panel report-controls report-export-result",
  );
  const download = editionDownload(
    result.artifact_id,
    result.edition_code,
    result,
    "pdf_url",
    "Скачать PDF отчёта",
  );
  download.download = "Отчёт класса · " + result.edition_code + ".pdf";
  panel.append(
    node("h2", "PDF отчёта готов"),
    node(
      "p",
      "Снимок результатов на " +
        new Date(result.generated_at).toLocaleString("ru-RU") +
        ". Новые проверки и исправления в этот файл не попадут - для них подготовьте свежий PDF.",
      "quiet",
    ),
    download,
  );
  $("classReport").querySelector(".class-heading").after(panel);
  panel.scrollIntoView({ block: "start" });
}
function renderReviewUpload(target, report) {
  const available = report.students.filter((s) => s.status === "not_submitted");
  if (!available.length && !reviewState.pending) return;
  const panel = node(
    "section",
    undefined,
    "panel review-upload report-controls",
  );
  panel.append(
    node("h2", "Добавить ответы ученика"),
    node(
      "p",
      "Один ученик за загрузку, до 5 фото PNG/JPEG, суммарно до 20 МБ. Снимайте без фамилии: достаточно номера задания и кода ученика.",
      "quiet",
    ),
  );
  const form = node("form"),
    fields = node("fieldset"),
    label = node("label", "Код ученика"),
    select = node("select");
  fields.className = "review-upload-fields";
  for (const s of available) {
    const option = node("option", s.code);
    option.value = s.id;
    select.append(option);
  }
  if (reviewState.pending) select.value = reviewState.pending.studentId;
  label.append(select);
  fields.append(label);
  const photos = node("input"),
    camera = node("input");
  photos.type = camera.type = "file";
  photos.accept = camera.accept = "image/png,image/jpeg";
  photos.multiple = true;
  camera.capture = "environment";
  photos.hidden = camera.hidden = true;
  photos.setAttribute("aria-label", "Выбрать фото ответов");
  camera.setAttribute("aria-label", "Снять фото ответов");
  const previews = node("div", undefined, "review-previews"),
    fileCount = node("p", "Фото не выбраны", "quiet");
  const draw = () => {
    previews.replaceChildren();
    fileCount.textContent = reviewState.files.length
      ? "Выбрано фото: " + reviewState.files.length
      : "Фото не выбраны";
    for (const [i, item] of reviewState.files.entries()) {
      const card = node("div", undefined, "review-preview");
      const img = node("img");
      img.src = item.url;
      img.alt = "Фото ответов " + (i + 1);
      card.append(
        img,
        classButton(
          "Убрать фото " + (i + 1),
          () => {
            URL.revokeObjectURL(item.url);
            reviewState.files.splice(i, 1);
            draw();
          },
          "ghost",
        ),
      );
      previews.append(card);
    }
  };
  const add = (input) => {
    const files = [...input.files];
    input.value = "";
    if (
      files.some(
        (f) => !/\.(png|jpe?g)$/i.test(f.name) || f.size > 15 * 1024 * 1024,
      ) ||
      files.length + reviewState.files.length > 5 ||
      [...files, ...reviewState.files.map((f) => f.file)].reduce(
        (n, f) => n + f.size,
        0,
      ) >
        20 * 1024 * 1024
    ) {
      notice("Выберите до 5 PNG/JPEG: каждое до 15 МБ, вместе до 20 МБ.", true);
      return;
    }
    reviewState.files.push(
      ...files.map((file) => ({ file, url: URL.createObjectURL(file) })),
    );
    draw();
  };
  photos.addEventListener("change", () => add(photos));
  camera.addEventListener("change", () => add(camera));
  const actions = node("div", undefined, "actions");
  actions.append(
    classButton("Снять фото", () => camera.click()),
    classButton("Из галереи", () => photos.click()),
  );
  const submit = node(
    "button",
    reviewState.pending ? "Повторить отправку фото" : "Распознать ответы",
    "button primary",
  );
  submit.type = "submit";
  fields.append(
    actions,
    photos,
    camera,
    fileCount,
    previews,
    node(
      "p",
      "Фото доступны только вам и удаляются из рабочего хранилища через 7 дней. Баллы и исправления сохраняются. Перед загрузкой убедитесь, что на фото нужный ученик.",
      "quiet",
    ),
  );
  fields.disabled = !!reviewState.pending;
  form.append(fields, submit);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    busy("Отправляем фото", async () => {
      if (!reviewState.pending) {
        if (!reviewState.files.length)
          throw new Error("Добавьте хотя бы одно фото ответов.");
        const data = new FormData();
        data.set("student_id", select.value);
        for (const item of reviewState.files) data.append("files", item.file);
        reviewState.pending = {
          assignmentId: report.assignment_id,
          studentId: select.value,
          body: data,
          key: crypto.randomUUID(),
        };
      }
      fields.disabled = true;
      const pending = reviewState.pending;
      try {
        const result = await request(
          `/api/v2/assignments/${pending.assignmentId}/submissions`,
          {
            method: "POST",
            headers: { "Idempotency-Key": pending.key },
            body: pending.body,
          },
        );
        reviewState.pending = null;
        clearReviewFiles();
        await openReview(result.review_id);
        await refreshJobs();
        pollJobs();
        notice(
          "Фото приняты. После распознавания проверьте ответы и подтвердите баллы.",
        );
      } catch (error) {
        if (error.status && error.status < 500) {
          reviewState.pending = null;
          fields.disabled = false;
        } else submit.textContent = "Повторить отправку фото";
        throw error;
      }
    });
  });
  panel.append(form);
  target.append(panel);
  draw();
}
async function openReview(id, ready = null) {
  await flushReviewDraft();
  clearTimeout(reviewState.timer);
  const r = ready || (await request("/api/v2/reviews/" + id)).review;
  resetReviewEditor();
  reviewState.current = r;
  classScreen("reviewView");
  const target = $("reviewView");
  target.replaceChildren(
    reviewButton(
      "← К отчёту класса",
      () => openClassReport(r.assignment_id),
      "ghost back-link",
    ),
  );
  const panel = node("section", undefined, "panel review-heading");
  panel.append(
    node("p", r.class_name + " · " + r.student_code, "eyebrow"),
    node("h1", r.title),
    node("p", reviewLabels[r.status] + " · Версия " + r.edition_code, "quiet"),
  );
  target.append(panel);
  if (r.status === "processing") {
    panel.append(
      node(
        "p",
        "Распознаём конечные ответы. Можно закрыть страницу: работа сохранена в кабинете.",
      ),
    );
    reviewState.timer = setTimeout(() => {
      if (
        !$("reviewView").hidden &&
        state.view === "classes" &&
        reviewState.current?.id === id
      )
        busy("Обновляем распознавание", () => openReview(id));
    }, 5000);
    classFocus(target);
    return;
  }
  if (r.status === "failed")
    panel.append(
      node(
        "p",
        r.error ||
          "Обработка прервалась. Удалите неудачную проверку и загрузите фото заново.",
        "job-error",
      ),
    );
  for (const warning of r.warnings)
    panel.append(node("p", warning, "review-warning"));
  if (r.photos.length) {
    const gallery = node("details", undefined, "panel review-gallery");
    gallery.open = true;
    gallery.append(node("summary", "Фото ответов · " + r.photos.length));
    for (const [i, url] of r.photos.entries()) {
      const link = node("a");
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener";
      const img = node("img");
      img.src = url;
      img.alt = "Страница ответов " + (i + 1);
      link.append(img);
      gallery.append(link);
    }
    gallery.append(
      node(
        "p",
        "Откройте снимок для увеличения. Фото удаляются через 7 дней после загрузки.",
        "quiet",
      ),
    );
    target.append(gallery);
  } else if (r.status !== "failed")
    panel.append(
      node(
        "p",
        "Срок хранения фото истёк. Распознанные ответы и история сохранены.",
        "quiet",
      ),
    );
  if (["needs_review", "confirmed"].includes(r.status))
    renderReviewForm(target, r);
  if (r.status !== "confirmed") {
    let ask = false;
    const remove = classButton(
      "Удалить черновик проверки",
      () => {
        if (!ask) {
          ask = true;
          remove.textContent = "Да, удалить фото и черновик";
          return;
        }
        busy("Удаляем черновик", async () => {
          await flushReviewDraft();
          await request(
            "/api/v2/reviews/" + id,
            classJson("DELETE", {
              revision: r.revision,
              draft_revision: reviewState.editor?.draftRevision ?? null,
            }),
          );
          resetReviewEditor();
          await openClassReport(r.assignment_id);
          notice("Черновик удалён. Можно загрузить фото заново.");
        });
      },
      "ghost",
    );
    target.append(remove);
  }
  classFocus(target);
}
function renderReviewForm(target, r) {
  const form = node("form", undefined, "review-form"),
    fields = [];
  const draft = r.draft;
  if (draft)
    form.append(
      node(
        "p",
        r.status === "confirmed"
          ? "Открыт сохранённый черновик исправлений. В отчёте пока прежние подтверждённые баллы. Для применения сверьте работу и подтвердите исправления."
          : "Ваши сохранённые правки восстановлены. Сверьте ответы и подтвердите результат, когда закончите.",
        "review-warning",
      ),
    );
  form.append(
    node(
      "h2",
      r.status === "confirmed"
        ? "Проверка и исправления"
        : "Проверьте ответы и баллы",
    ),
    node(
      "p",
      "Каждое задание — 0 или 1 балл. Совпадение с ключом — подсказка, итог подтверждаете вы. Развёрнутое решение здесь не оценивается.",
      "quiet",
    ),
  );
  const total = node("p", undefined, "review-total");
  const confirm = node(
    "button",
    r.status === "confirmed"
      ? "Подтвердить исправления"
      : "Подтвердить результат",
    "button primary",
  );
  confirm.type = "submit";
  const reviewed = node("input");
  reviewed.type = "checkbox";
  const refreshTotal = () => {
    const done = fields.filter((f) => f.score.value !== "");
    total.textContent = `Баллы: ${done.reduce((n, f) => n + Number(f.score.value), 0)} из ${r.tasks.length} · Оценено заданий: ${done.length} из ${r.tasks.length}`;
    confirm.disabled = !reviewed.checked || done.length !== r.tasks.length;
  };
  for (const [i, task] of r.tasks.entries()) {
    const answer = (draft?.answers || r.answers)[i],
      card = node("section", undefined, "panel review-answer");
    card.append(node("h3", "Задание " + (i + 1)));
    const question = node("p"),
      expected = node("p", undefined, "review-key");
    mathPreview(question, task.question);
    mathPreview(
      expected,
      "Эталон: " + (task.answer || "Не заполнен — проверьте вручную"),
    );
    const caption = node(
      "p",
      answer.teacher_edited
        ? "Ответ уточнён учителем. Сверьте выставленные баллы."
        : answer.state === "blank"
          ? "ИИ: поле ответа пустое — нужен ваш выбор баллов."
          : answer.state === "unclear"
            ? "ИИ: ответ неразборчив или номер не найден — сверьте фото."
            : answer.comparison === "matches"
              ? "Прочитанный ответ совпадает с ключом. Сверьте с фото."
              : "Прочитанный ответ требует сравнения с ключом.",
      answer.state === "readable" ? "quiet" : "review-warning",
    );
    const textLabel = node("label", "Прочитанный ответ · задание " + (i + 1)),
      text = node("textarea");
    text.value = answer.text;
    text.maxLength = 2000;
    text.rows = 2;
    textLabel.append(text);
    const scoreLabel = node("label", "Баллы · задание " + (i + 1)),
      score = node("select");
    for (const [value, label] of [
      ["", "Выберите баллы"],
      ["0", "0 — неверно / нет ответа"],
      ["1", "1 — верно"],
    ]) {
      const option = node("option", label);
      option.value = value;
      score.append(option);
    }
    score.value = answer.score === null ? "" : String(answer.score);
    scoreLabel.append(score);
    const noteLabel = node("label", "Комментарий · задание " + (i + 1)),
      note = node("input");
    note.value = answer.comment;
    note.maxLength = 500;
    noteLabel.append(note);
    text.addEventListener("input", () => {
      score.value = "";
      reviewed.checked = false;
      caption.textContent = "Ответ изменён. Укажите баллы после проверки.";
      refreshTotal();
      editReviewDraft();
    });
    score.addEventListener("change", () => {
      reviewed.checked = false;
      refreshTotal();
      editReviewDraft();
    });
    note.addEventListener("input", () => {
      reviewed.checked = false;
      refreshTotal();
      editReviewDraft();
    });
    fields.push({ id: task.id, text, score, note });
    card.append(question, expected, caption, textLabel, scoreLabel, noteLabel);
    form.append(card);
  }
  const controls = node("section", undefined, "panel review-confirmation"),
    commentLabel = node("label", "Комментарий к работе"),
    comment = node("textarea");
  comment.value = draft?.comment ?? r.comment;
  comment.maxLength = 2000;
  comment.rows = 3;
  commentLabel.append(comment);
  comment.addEventListener("input", () => {
    reviewed.checked = false;
    refreshTotal();
    editReviewDraft();
  });
  const check = node("label", undefined, "review-attestation");
  check.append(
    reviewed,
    node(
      "span",
      "Я сверил фото, код ученика, версию листа и баллы каждого задания.",
    ),
  );
  reviewed.addEventListener("change", refreshTotal);
  const body = (action) => ({
    revision: r.revision,
    draft_revision: reviewState.editor?.draftRevision ?? null,
    action,
    reviewed: reviewed.checked,
    comment: comment.value,
    answers: fields.map((f) => ({
      task_id: f.id,
      text: f.text.value,
      score: f.score.value === "" ? null : Number(f.score.value),
      comment: f.note.value,
    })),
  });
  const saveStatus = node(
    "p",
    draft
      ? "Правки восстановлены из вашего кабинета. Подтверждение сверки нужно поставить заново."
      : "Правки сохраняются автоматически. Итоговые баллы нужно подтвердить.",
    "quiet review-save-status",
  );
  saveStatus.setAttribute("role", "status");
  reviewState.editor = {
    id: r.id,
    body,
    status: saveStatus,
    draftRevision: draft?.revision ?? null,
    changed: 0,
    saved: 0,
    saving: null,
    timer: null,
  };
  const actions = node("div", undefined, "actions");
  actions.append(
    reviewButton("Сохранить черновик", async () => {
      await flushReviewDraft();
      if (r.status !== "confirmed") {
        await request(
          "/api/v2/reviews/" + r.id,
          classJson("PUT", body("save")),
        );
        resetReviewEditor();
        await openReview(r.id);
      }
      notice(
        r.status === "confirmed"
          ? "Правки сохранены. Прежние баллы остаются в отчёте до нового подтверждения."
          : "Черновик сохранён. В итоговой статистике его пока нет.",
      );
    }),
  );
  actions.append(confirm);
  const otherActions = node("details", undefined, "review-recovery");
  otherActions.append(node("summary", "Другие действия с правками"));
  const recovery = node("div", undefined, "actions");
  recovery.append(
    classButton(
      "Скачать мои правки",
      () => {
        const value = body();
        const lines = [
          r.class_name,
          r.title,
          "Ученик: " + r.student_code,
          "Версия листа: " + r.edition_code,
          "Это черновик, а не подтверждённый результат.",
          ...value.answers.flatMap((a, i) => [
            "",
            "Задание " + (i + 1),
            "Ответ: " + (a.text || "(пусто)"),
            "Баллы: " + (a.score === null ? "не выбраны" : a.score),
            "Комментарий: " + a.comment,
          ]),
          "",
          "Комментарий к работе: " + value.comment,
        ];
        const url = URL.createObjectURL(
          new Blob([lines.join("\n")], { type: "text/plain;charset=utf-8" }),
        );
        const link = node("a");
        link.href = url;
        link.download = "Мои правки · " + r.student_code + ".txt";
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      },
      "ghost",
    ),
  );
  let discardAsked = false;
  const discard = classButton(
    "Отменить мои правки",
    () => {
      if (!discardAsked) {
        discardAsked = true;
        discard.textContent = "Да, вернуть сохранённый результат";
        return;
      }
      busy("Отменяем правки", async () => {
        await flushReviewDraft();
        await request(
          `/api/v2/reviews/${r.id}/draft`,
          classJson("DELETE", {
            revision: r.revision,
            draft_revision: reviewState.editor.draftRevision,
          }),
        );
        resetReviewEditor();
        await openReview(r.id);
        notice("Черновик правок удалён. Сохранённый результат восстановлен.");
      });
    },
    "ghost",
  );
  recovery.append(discard);
  let reopenAsked = false;
  const reopen = classButton(
    "Открыть сохранённую версию",
    () => {
      if (hasUnsavedReview() && !reopenAsked) {
        reopenAsked = true;
        reopen.textContent = "Да, открыть без несохранённых правок";
        notice(
          "Перед открытием можно скачать текущие правки. Сохранённый в кабинете черновик останется.",
        );
        return;
      }
      busy("Открываем сохранённую проверку", async () => {
        // Read first: a network error must leave the current form intact.
        const fresh = (await request(`/api/v2/reviews/${r.id}`)).review;
        resetReviewEditor();
        await openReview(r.id, fresh);
      });
    },
    "ghost",
  );
  recovery.append(reopen);
  otherActions.append(recovery);
  controls.append(
    commentLabel,
    total,
    saveStatus,
    check,
    actions,
    otherActions,
  );
  form.append(controls);
  target.append(form);
  refreshTotal();
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    busy("Подтверждаем результат", async () => {
      await flushReviewDraft();
      await request(
        "/api/v2/reviews/" + r.id,
        classJson("PUT", body("confirm")),
      );
      resetReviewEditor();
      await openClassReport(r.assignment_id);
      notice("Результат подтверждён и учтён в отчёте класса.");
    });
  });
  const history = node("details", undefined, "panel review-history");
  history.append(node("summary", "История проверки"));
  history.addEventListener("toggle", async () => {
    if (!history.open || history.dataset.loaded) return;
    try {
      const data = (await request(`/api/v2/reviews/${r.id}/history`)).history;
      for (const h of data) {
        const entry = node("section", undefined, "review-history-entry");
        entry.append(
          node(
            "p",
            `Версия ${h.revision} · ${{ recognized: "Распознано", save: "Сохранён черновик", confirm: "Подтверждено учителем" }[h.action]} · ${new Date(h.created_at).toLocaleString("ru-RU")}`,
            "quiet",
          ),
        );
        const show = (value) =>
          value === null
            ? "не оценено"
            : value === ""
              ? "(пусто)"
              : String(value);
        for (const change of h.changes) {
          entry.append(node("h3", "Задание " + change.number));
          for (const [key, values] of Object.entries(change.fields))
            entry.append(
              node(
                "p",
                { text: "Ответ", score: "Баллы", comment: "Комментарий" }[key] +
                  ": " +
                  show(values.before) +
                  " → " +
                  show(values.after),
              ),
            );
        }
        if (h.comment_change)
          entry.append(
            node(
              "p",
              "Комментарий к работе: " +
                show(h.comment_change.before) +
                " → " +
                show(h.comment_change.after),
            ),
          );
        if (!h.changes.length && !h.comment_change)
          entry.append(
            node(
              "p",
              h.action === "recognized"
                ? "Получена исходная расшифровка ответов."
                : "Ответы, баллы и комментарии не менялись.",
              "quiet",
            ),
          );
        history.append(entry);
      }
      history.dataset.loaded = "true";
    } catch (error) {
      notice(error.message, true);
    }
  });
  target.append(history);
}
window.addEventListener(
  "afterprint",
  () => delete document.body.dataset.printReport,
);

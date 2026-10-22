"use strict";
const reviewState = {
  current: null,
  report: null,
  files: [],
  assignmentId: null,
  pending: null,
  timer: null,
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
function clearReviewFiles() {
  for (const f of reviewState.files) URL.revokeObjectURL(f.url);
  reviewState.files = [];
}
async function openClassReport(id) {
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
  target.replaceChildren(
    reviewButton(
      "← К назначенной работе",
      () => openAssignment(id),
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
          : ""),
      "quiet",
    ),
  );
  heading.append(text);
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
        : `Средний балл: ${data.summary.average} из ${data.summary.maximum} · Выполнение: ${data.summary.percent}%`,
    ),
    node(
      "p",
      `В расчёте только подтверждённые работы: ${data.summary.confirmed} из ${data.summary.total}. Черновики и несданные работы исключены.`,
      "quiet",
    ),
    node("p", data.recommendation),
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
async function openReview(id) {
  clearTimeout(reviewState.timer);
  const r = (await request("/api/v2/reviews/" + id)).review;
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
          await request(
            "/api/v2/reviews/" + id,
            classJson("DELETE", { revision: r.revision }),
          );
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
  form.append(
    node(
      "h2",
      r.status === "confirmed"
        ? "Подтверждённый результат"
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
    const answer = r.answers[i],
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
    });
    score.addEventListener("change", () => {
      reviewed.checked = false;
      refreshTotal();
    });
    fields.push({ id: task.id, text, score, note });
    card.append(question, expected, caption, textLabel, scoreLabel, noteLabel);
    form.append(card);
  }
  const controls = node("section", undefined, "panel review-confirmation"),
    commentLabel = node("label", "Комментарий к работе"),
    comment = node("textarea");
  comment.value = r.comment;
  comment.maxLength = 2000;
  comment.rows = 3;
  commentLabel.append(comment);
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
  const actions = node("div", undefined, "actions");
  if (r.status !== "confirmed")
    actions.append(
      reviewButton("Сохранить черновик", async () => {
        await request(
          "/api/v2/reviews/" + r.id,
          classJson("PUT", body("save")),
        );
        await openReview(r.id);
        notice("Черновик сохранён. В итоговой статистике его пока нет.");
      }),
    );
  actions.append(confirm);
  controls.append(commentLabel, total, check, actions);
  form.append(controls);
  target.append(form);
  refreshTotal();
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    busy("Подтверждаем результат", async () => {
      await request(
        "/api/v2/reviews/" + r.id,
        classJson("PUT", body("confirm")),
      );
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
      for (const h of data)
        history.append(
          node(
            "p",
            `Версия ${h.revision} · ${{ recognized: "Распознано", save: "Сохранён черновик", confirm: "Подтверждено учителем" }[h.action]} · ${new Date(h.created_at).toLocaleString("ru-RU")}`,
            "quiet",
          ),
        );
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

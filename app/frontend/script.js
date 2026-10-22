"use strict";
const $ = (id) => document.getElementById(id);
const storageKey = "listok.materials.v1";
const state = {
  sheet: null,
  source: "",
  files: [],
  urls: [],
  result: null,
  step: 1,
  busy: false,
  status: null,
  savedId: null,
  revision: null,
  materials: [],
  auth: null,
  dirty: false,
  view: "workspace",
  origin: null,
  library: [],
  libraryPage: 1,
  publication: null,
  publishDraft: null,
};
function notice(message, error = false) {
  $("notice").textContent = message;
  $("notice").classList.toggle("error", error);
  $("notice").hidden = !message;
}
function node(tag, text, cls) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (cls) n.className = cls;
  return n;
}
function subject() {
  return document.querySelector('input[name="subject"]:checked').value;
}
function taskCount(count) {
  const word =
    count % 100 >= 11 && count % 100 <= 14
      ? "заданий"
      : count % 10 === 1
        ? "задание"
        : [2, 3, 4].includes(count % 10)
          ? "задания"
          : "заданий";
  return count + " " + word;
}
function saved() {
  try {
    const v = JSON.parse(localStorage.getItem(storageKey) || "[]");
    return Array.isArray(v)
      ? v.filter(
          (x) => x && x.id && x.worksheet && Array.isArray(x.worksheet.tasks),
        )
      : [];
  } catch {
    return [];
  }
}

function updateCount() {
  $("savedCount").textContent = state.materials.length;
}
function markDirty(value) {
  state.dirty = value;
  const method = value
    ? "enableClosingConfirmation"
    : "disableClosingConfirmation";
  window.WebApp?.[method]?.();
  $("saveStatus").textContent = value ? "Есть несохранённые изменения" : "";
}
function invalidate() {
  markDirty(true);
  state.result = null;
  $("reviewCheckbox").checked = false;
  $("compileBtn").disabled = true;
}
function step(number) {
  state.step = number;
  document.body.dataset.step = number;
  if (window.WebApp?.BackButton) {
    if (number > 1) window.WebApp.BackButton.show();
    else window.WebApp.BackButton.hide();
  }
  for (let i = 1; i <= 4; i++) $("step" + i).hidden = i !== number;
  document.querySelectorAll("[data-step]").forEach((n) => {
    const v = Number(n.dataset.step);
    n.classList.toggle("current", v === number);
    n.classList.toggle("done", v < number);
    if (v === number) n.setAttribute("aria-current", "step");
    else n.removeAttribute("aria-current");
  });
  const tips = [
    null,
    [
      "Хорошее фото — точнее результат",
      "Снимайте страницу сверху, при хорошем свете. Проверьте, что видны все числа, формулы и края заданий.",
    ],
    [
      "Содержание под вашим контролем",
      "Проверьте распознанные числа и ответы. Нейросеть может ошибаться, даже если формула выглядит убедительно.",
    ],
    [
      "Оставьте место для мысли",
      "Для длинных условий выбирайте один столбец и меньше заданий на странице. Для коротких упражнений подойдёт компактный список.",
    ],
    [
      "Сохраните удачную основу",
      "Сохранённый лист можно открыть в «Моих материалах», изменить и собрать заново. Материалы сохраняются в вашем профиле.",
    ],
  ];
  $("tipTitle").textContent = tips[number][0];
  $("tipText").textContent = tips[number][1];
  const heading = $("step" + number).querySelector("h2");
  heading.tabIndex = -1;
  heading.focus({ preventScroll: true });
  if (number !== 1)
    $("step" + number).scrollIntoView({ behavior: "smooth", block: "start" });
}
function showView(view, refresh = true) {
  state.view = view;
  for (const [name, id] of Object.entries({
    workspace: "workspace",
    saved: "savedView",
    library: "libraryView",
    publish: "publishView",
  }))
    $(id).hidden = view !== name;
  $("createNav").classList.toggle("active", view === "workspace");
  $("savedNav").classList.toggle("active", ["saved", "publish"].includes(view));
  $("libraryNav").classList.toggle("active", view === "library");
  if (view === "saved" && refresh)
    busy("Загружаем ваши материалы", refreshMaterials);
  if (view === "library" && refresh) {
    showLibraryList();
    busy("Загружаем библиотеку", () => refreshLibrary());
  }
  if (window.WebApp?.BackButton) {
    if (view !== "workspace" || state.step > 1) window.WebApp.BackButton.show();
    else window.WebApp.BackButton.hide();
  }
}
async function request(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (
    options.method &&
    !["GET", "HEAD"].includes(options.method.toUpperCase()) &&
    state.auth?.csrf_token
  )
    headers.set("X-CSRF-Token", state.auth.csrf_token);
  const response = await fetch(url, {
    ...options,
    headers,
    credentials: "same-origin",
  });
  let body;
  try {
    body = await response.json();
  } catch {
    throw new Error("Сервер не ответил. Проверьте подключение и повторите.");
  }
  if (!response.ok) {
    if (response.status === 401) {
      state.auth = null;
      state.materials = [];
      updateCount();
      $("loginPanel").hidden = false;
      $("loginHint").textContent =
        "Сессия завершилась. Откройте ЛистОК заново через MAX. Черновик останется на экране до перезагрузки.";
    }
    const error = new Error(body.error || "Не удалось выполнить запрос.");
    error.status = response.status;
    throw error;
  }
  return body;
}
async function busy(title, action) {
  if (state.busy) return;
  state.busy = true;
  notice("");
  $("busyTitle").textContent = title;
  $("busyOverlay").hidden = false;
  document.querySelector("main").inert = true;
  document.querySelector("header").inert = true;
  try {
    await action();
  } catch (e) {
    notice(e.message || "Не удалось выполнить действие.", true);
    $("notice").scrollIntoView({ behavior: "smooth", block: "center" });
  } finally {
    state.busy = false;
    $("busyOverlay").hidden = true;
    document.querySelector("main").inert = false;
    document.querySelector("header").inert = false;
  }
}
function mathPreview(target, text) {
  target.replaceChildren();
  const parts = text.split("$");
  parts.forEach((part, index) => {
    if (index % 2 && index < parts.length - 1 && window.katex) {
      const span = node("span");
      try {
        window.katex.render(part, span, {
          throwOnError: false,
          trust: false,
          strict: false,
          maxExpand: 100,
          output: "htmlAndMathml",
        });
      } catch {
        span.textContent = part;
      }
      target.append(span);
    } else target.append(document.createTextNode(part));
  });
}
function renderTasks() {
  $("titleInput").value = state.sheet.title;
  $("sourceLabel").textContent =
    state.source === "manual_demo"
      ? "Учебный пример подготовлен вручную. ИИ не использовался."
      : state.origin
        ? "Основа: «" +
          state.origin.title +
          "», автор — " +
          state.origin.author +
          ". Проверьте материал для своего класса."
        : "Черновик: проверьте распознанные условия и ответы.";
  $("taskList").replaceChildren();
  state.sheet.tasks.forEach((task, index) => {
    const card = node("article", undefined, "task-card"),
      header = node("div", undefined, "task-card-header");
    header.append(node("span", "ЗАДАНИЕ " + (index + 1)));
    const remove = node("button", "Удалить");
    remove.type = "button";
    remove.setAttribute("aria-label", "Удалить задание " + (index + 1));
    remove.disabled = state.sheet.tasks.length === 1;
    remove.addEventListener("click", () => {
      state.sheet.tasks.splice(index, 1);
      invalidate();
      renderTasks();
    });
    header.append(remove);
    card.append(header);
    const content = node("div", undefined, "task-content");
    for (const [field, label] of [
      ["question", "Условие"],
      ["answer", "Ответ для учителя"],
    ]) {
      const block = node(
          "div",
          undefined,
          field === "answer" ? "answer-block" : "question-block",
        ),
        id = "task-" + index + "-" + field;
      const title = node("label", label, "field-label");
      title.htmlFor = id;
      const input = node("textarea");
      input.id = id;
      input.setAttribute("aria-label", label + " задания " + (index + 1));
      input.value = task[field];
      input.maxLength = field === "question" ? 4000 : 2000;
      input.rows = field === "question" ? 3 : 2;
      const preview = node("div", undefined, "math-preview");
      mathPreview(preview, input.value);
      input.addEventListener("input", () => {
        task[field] = input.value;
        if (
          task.note.startsWith("Ответ к этому числовому выражению проверен")
        ) {
          task.note = "";
          card.querySelector(".task-note")?.remove();
        }
        invalidate();
        mathPreview(preview, input.value);
      });
      const edit = node("details", undefined, "task-edit");
      edit.open = field === "question" && !task.question.trim();
      edit.append(
        node(
          "summary",
          field === "question" ? "Изменить условие" : "Изменить ответ",
        ),
        input,
      );
      block.append(title, preview, edit);
      content.append(block);
    }
    if (task.note) content.append(node("p", task.note, "task-note"));
    card.append(content);
    $("taskList").append(card);
  });
  $("addTaskBtn").disabled = state.sheet.tasks.length >= 30;
}
function loadSheet(data, source, id = null, origin = null) {
  state.sheet = structuredClone(data);
  state.source = source;
  state.savedId = id;
  state.origin = origin;
  $("saveBtn").textContent = id
    ? "Сохранить изменения"
    : "Сохранить в мои материалы";
  state.revision = null;
  invalidate();
  markDirty(!id);
  renderTasks();
  showView("workspace");
  step(2);
}
function renderSettings() {
  $("teacherInput").value = state.sheet.teacher_name || "";
  $("gradeInput").value = state.sheet.grade || "";
  document
    .querySelectorAll('[name="field"]')
    .forEach((n) => (n.checked = n.value === state.sheet.settings.field));
  $("columnsSelect").value = state.sheet.settings.columns;
  $("countSelect").value = state.sheet.settings.tasks_per_page;
  $("compileBtn").disabled =
    !$("reviewCheckbox").checked || !state.status?.latex_ready;
  summary();
}
function summary() {
  const count = Number($("countSelect").value);
  $("pageSummary").textContent =
    "A4 · заданий: " +
    state.sheet.tasks.length +
    " · страниц с заданиями: " +
    Math.ceil(state.sheet.tasks.length / count);
}
function readSettings() {
  state.sheet.teacher_name = $("teacherInput").value;
  state.sheet.grade = $("gradeInput").value;
  state.sheet.settings = {
    columns: Number($("columnsSelect").value),
    tasks_per_page: Number($("countSelect").value),
    field: document.querySelector('[name="field"]:checked').value,
  };
}
function validTasks() {
  if (!state.sheet.title.trim()) {
    notice("Укажите тему рабочего листа.", true);
    $("titleInput").focus();
    return false;
  }
  if (state.sheet.tasks.some((t) => !t.question.trim())) {
    notice("Заполните условия всех заданий или удалите пустые.", true);
    return false;
  }
  return true;
}
async function renderResult() {
  $("resultSheetTitle").textContent = state.sheet.title;
  $("resultTasks").replaceChildren();
  state.sheet.tasks.forEach((task, index) => {
    const card = node("div", undefined, "result-task");
    card.append(node("strong", "Задание " + (index + 1)));
    const content = node("div");
    mathPreview(content, task.question);
    card.append(content);
    $("resultTasks").append(card);
  });
  $("downloadSheet").href = state.result.pdf_url;
  $("downloadKeys").href = state.result.keys_url;
  $("downloadTex").href = state.result.tex_url;
  $("downloadMarp").hidden = !state.result.marp_url;
  if (state.result.marp_url) $("downloadMarp").href = state.result.marp_url;
  $("pdfPreview").src = state.result.pdf_url + "#toolbar=0";
  if (window.WebApp?.downloadFile && state.result.artifact_id) {
    const links = await request("/api/v2/exports/" + state.result.artifact_id, {
      method: "POST",
    });
    for (const [id, key, name] of [
      ["downloadSheet", "pdf_url", "Рабочий лист.pdf"],
      ["downloadKeys", "keys_url", "Ответы.pdf"],
      ["downloadTex", "tex_url", "Рабочий лист.tex"],
      ["downloadMarp", "marp_url", "ЛистОК Marp.zip"],
    ]) {
      if (!links[key]) continue;
      $(id).onclick = (event) => {
        event.preventDefault();
        if (Date.now() >= links.expires_at * 1000) {
          busy("Обновляем ссылку", async () => {
            await renderResult();
            notice("Ссылка готова. Нажмите кнопку скачивания ещё раз.");
          });
          return;
        }
        Promise.resolve()
          .then(() =>
            window.WebApp.downloadFile(
              new URL(links[key], location.origin).href,
              name,
            ),
          )
          .catch(() =>
            notice("MAX не смог скачать файл. Повторите скачивание.", true),
          );
      };
    }
  }
  document
    .querySelectorAll("[data-variant]")
    .forEach((b) => (b.disabled = !state.status?.ai_ready));
}
async function saveCurrent(copy = false) {
  if (!validTasks()) throw new Error("Проверьте тему и условия заданий.");
  const id = copy ? null : state.savedId;
  const result = await request("/api/v2/materials" + (id ? "/" + id : ""), {
    method: id ? "PUT" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      worksheet: state.sheet,
      source: state.source,
      revision: state.revision,
      artifact_id: copy ? null : state.result?.artifact_id || null,
      origin_material_id: copy ? state.savedId : null,
    }),
  });
  state.savedId = result.material.id;
  state.revision = result.material.revision;
  state.origin = result.material.origin;
  if (copy) state.result = null;
  markDirty(false);
  $("saveStatus").textContent = "Сохранено в профиле";
  $("saveBtn").textContent = "Сохранить изменения";
  await refreshMaterials();
  return state.savedId;
}
async function refreshMaterials() {
  if (!state.auth?.authenticated) return;
  const result = await request("/api/v2/materials");
  state.materials = result.materials;
  updateCount();
  renderSaved();
}
function renderSaved() {
  $("savedList").replaceChildren();
  $("importLocalBtn").hidden = !saved().length;
  const query = $("materialSearch").value.trim().toLocaleLowerCase("ru");
  const items = state.materials.filter((item) =>
    (
      item.worksheet.title +
      " " +
      item.worksheet.tasks.map((t) => t.question).join(" ")
    )
      .toLocaleLowerCase("ru")
      .includes(query),
  );
  if ($("materialSort").value === "title")
    items.sort((a, b) =>
      a.worksheet.title.localeCompare(b.worksheet.title, "ru"),
    );
  if (!items.length) {
    const empty = node("div", undefined, "empty-state");
    empty.append(
      node(
        "h2",
        query ? "Ничего не нашлось" : "Здесь появятся ваши рабочие листы",
      ),
      node(
        "p",
        query
          ? "Попробуйте другое слово из темы или задания."
          : "Можно сохранить черновик сразу после проверки заданий.",
      ),
    );
    $("savedList").append(empty);
    return;
  }
  for (const item of items) {
    const card = node("article", undefined, "saved-card");
    card.append(
      node(
        "span",
        item.worksheet.subject === "math" ? "МАТЕМАТИКА" : "ФИЗИКА",
        "eyebrow",
      ),
      node("h2", item.worksheet.title),
      node(
        "p",
        taskCount(item.worksheet.tasks.length) +
          " · " +
          new Date(item.updated).toLocaleDateString("ru-RU"),
      ),
      node("span", item.result ? "PDF готов" : "Черновик", "material-badge"),
    );
    if (item.publication_id)
      card.append(
        node("span", "В библиотеке", "material-badge publication-badge"),
      );
    if (item.origin)
      card.append(node("p", "Основа: " + item.origin.author, "quiet"));
    const actions = node("div", undefined, "actions");
    const open = node("button", "Открыть", "button secondary");
    const remove = node("button", "Удалить", "button ghost");
    open.addEventListener("click", () => {
      if (
        state.dirty &&
        !window.confirm(
          "Открыть другой материал? Несохранённые изменения текущего листа будут потеряны.",
        )
      )
        return;
      busy("Открываем материал", async () => {
        const fresh = (await request("/api/v2/materials/" + item.id)).material;
        loadSheet(fresh.worksheet, fresh.source, fresh.id, fresh.origin);
        state.revision = fresh.revision;
        state.result = fresh.result;
        if (state.result) {
          await renderResult();
          step(4);
        }
      });
    });
    remove.addEventListener("click", () => {
      if (
        !window.confirm(
          "Удалить лист «" +
            item.worksheet.title +
            "» и его PDF из профиля?" +
            (item.publication_id
              ? " Публикация тоже исчезнет из библиотеки. Копии коллег останутся у них."
              : ""),
        )
      )
        return;
      busy("Удаляем материал", async () => {
        await request("/api/v2/materials/" + item.id, {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ revision: item.revision }),
        });
        if (state.savedId === item.id) {
          state.savedId = null;
          state.revision = null;
          state.result = null;
          markDirty(true);
        }
        await refreshMaterials();
        notice("Материал удалён.");
      });
    });
    const share = node(
      "button",
      item.publication_id ? "Открыть публикацию" : "Поделиться",
      "button secondary",
    );
    share.addEventListener("click", () =>
      busy("Открываем материал", async () => {
        if (item.publication_id) await openPublication(item.publication_id);
        else await preparePublication(item.id);
      }),
    );
    actions.append(open, share, remove);
    card.append(actions);
    $("savedList").append(card);
  }
}
function ratingText(item) {
  return item.rating_count
    ? "★ " +
        item.rating.toLocaleString("ru-RU", { maximumFractionDigits: 2 }) +
        " из 5 · оценок: " +
        item.rating_count
    : "Пока без оценок";
}
function showLibraryList() {
  $("libraryBrowse").hidden = false;
  $("libraryDetail").hidden = true;
}
function backToLibrary() {
  showLibraryList();
  busy("Обновляем библиотеку", () => refreshLibrary());
}
async function refreshLibrary(append = false) {
  const page = append ? state.libraryPage + 1 : 1;
  const params = new URLSearchParams({
    q: $("librarySearch").value.trim(),
    subject: $("librarySubject").value,
    sort: $("librarySort").value,
    page: String(page),
  });
  const result = await request("/api/v2/library?" + params);
  const combined = append
    ? [...state.library, ...result.publications]
    : result.publications;
  state.library = [
    ...new Map(combined.map((item) => [item.id, item])).values(),
  ];
  state.libraryPage = result.page;
  $("libraryCount").textContent = "Материалов: " + result.total;
  $("libraryMore").hidden = !result.has_more;
  renderLibrary();
}
function renderLibrary() {
  const target = $("libraryList");
  target.replaceChildren();
  if (!state.library.length) {
    const filtered =
      $("librarySearch").value.trim() ||
      $("librarySubject").value ||
      $("librarySort").value === "mine";
    const empty = node("div", undefined, "empty-state");
    empty.append(
      node(
        "h2",
        filtered
          ? "Таких материалов пока нет"
          : "Поделитесь первым рабочим листом",
      ),
      node(
        "p",
        filtered
          ? "Измените запрос или фильтры. Свои листы можно опубликовать из «Моих материалов»."
          : "В библиотеке будут листы, которые учителя решили открыть коллегам. Оценки появятся после отзывов.",
      ),
    );
    target.append(empty);
    return;
  }
  for (const item of state.library) {
    const card = node("article", undefined, "saved-card library-card");
    card.append(
      node(
        "p",
        (item.subject === "math" ? "МАТЕМАТИКА" : "ФИЗИКА") +
          (item.grade ? " · " + item.grade : ""),
        "eyebrow",
      ),
      node("h2", item.title),
      node("p", "Автор: " + item.author, "library-author"),
      node(
        "p",
        item.description || "Рабочий лист для подготовки к уроку.",
        "library-description",
      ),
      node(
        "p",
        taskCount(item.task_count) + " · взяли за основу: " + item.copies,
      ),
      node("div", ratingText(item), "rating-summary"),
    );
    if (item.is_owner)
      card.append(node("span", "Ваша публикация", "material-badge"));
    const open = node("button", "Посмотреть задания", "button secondary");
    open.addEventListener("click", () =>
      busy("Открываем публикацию", () => openPublication(item.id)),
    );
    card.append(open);
    target.append(card);
  }
}
function previewTasks(target, tasks, openAnswers = false) {
  target.replaceChildren();
  tasks.forEach((task, i) => {
    const card = node("section", undefined, "library-task");
    const question = node("div", undefined, "math-preview");
    mathPreview(question, task.question);
    card.append(node("h3", "Задание " + (i + 1)), question);
    const answer = node("details", undefined, "task-edit");
    answer.open = openAnswers;
    const content = node("div", undefined, "math-preview");
    mathPreview(content, task.answer || "Ответ не указан");
    answer.append(node("summary", "Ответ для учителя"), content);
    if (task.note) answer.append(node("p", task.note, "quiet"));
    card.append(answer);
    target.append(card);
  });
}
function renderPublication(item) {
  state.publication = item;
  showView("library", false);
  $("libraryBrowse").hidden = true;
  $("libraryDetail").hidden = false;
  $("detailSubject").textContent =
    (item.subject === "math" ? "МАТЕМАТИКА" : "ФИЗИКА") +
    (item.grade ? " · " + item.grade : "");
  $("detailTitle").textContent = item.title;
  $("detailAuthor").textContent =
    "Автор: " + item.author + " · " + taskCount(item.task_count);
  $("detailDescription").textContent = item.description;
  $("detailOrigin").hidden = !item.origin;
  $("detailOrigin").textContent = item.origin
    ? "Основа: «" + item.origin.title + "», " + item.origin.author
    : "";
  renderPublicationRating(item);
  previewTasks($("detailTasks"), item.worksheet.tasks);
  $("withdrawPublication").hidden = !item.is_owner;
  $("withdrawConfirm").hidden = true;
  $("withdrawPublication").setAttribute("aria-expanded", "false");
  $("withdrawPublication").setAttribute("aria-controls", "withdrawConfirm");
  $("detailTitle").tabIndex = -1;
  $("detailTitle").focus({ preventScroll: true });
  $("libraryBack").scrollIntoView({ behavior: "smooth", block: "start" });
}
function renderPublicationRating(item) {
  $("detailRating").textContent = ratingText(item);
  $("ratingHint").textContent = item.is_owner
    ? "Это ваш материал. Его смогут оценить коллеги."
    : item.my_rating
      ? "Ваша оценка: " + item.my_rating + " из 5. Её можно изменить."
      : "Материал пригодился? Поставьте свою оценку.";
  $("ratingStars").replaceChildren();
  $("ratingStars").hidden = item.is_owner;
  if (item.is_owner) return;
  for (let stars = 1; stars <= 5; stars++) {
    const button = node("button", "★", "star-button");
    button.type = "button";
    button.classList.toggle("filled", stars <= (item.my_rating || 0));
    button.setAttribute("aria-label", "Оценить на " + stars + " из 5");
    button.setAttribute("aria-pressed", String(stars === item.my_rating));
    button.addEventListener("click", () =>
      busy("Сохраняем оценку", async () => {
        const result = await request("/api/v2/library/" + item.id + "/rating", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ stars }),
        });
        state.publication = result.publication;
        renderPublicationRating(result.publication);
        // Refresh the list when returning; retain the preview and scroll position.
        await refreshLibrary();
      }),
    );
    $("ratingStars").append(button);
  }
}
async function openPublication(id) {
  renderPublication((await request("/api/v2/library/" + id)).publication);
}
async function preparePublication(id) {
  if (state.savedId === id && state.dirty)
    throw new Error(
      "Сначала сохраните изменения открытого листа, затем поделитесь им.",
    );
  const material = (await request("/api/v2/materials/" + id)).material;
  if (material.publication_id) return openPublication(material.publication_id);
  state.publishDraft = material;
  $("publishTitle").textContent = material.worksheet.title;
  $("publishAuthor").value =
    state.auth?.user?.kind === "max" ? state.auth.user.first_name || "" : "";
  $("publishDescription").value = "";
  $("publishReviewed").checked = false;
  previewTasks($("publishTasks"), material.worksheet.tasks, true);
  showView("publish", false);
  $("cancelPublish").scrollIntoView({ behavior: "smooth", block: "start" });
}
function renderFiles() {
  state.urls.forEach((url) => URL.revokeObjectURL(url));
  state.urls = [];
  $("fileList").replaceChildren();
  state.files.forEach((file, index) => {
    const row = node("div", undefined, "file-item"),
      image = node("img");
    image.alt = "Фото " + (index + 1);
    image.src = URL.createObjectURL(file);
    state.urls.push(image.src);
    const remove = node("button", "×");
    remove.setAttribute("aria-label", "Убрать фото " + (index + 1));
    remove.addEventListener("click", () => {
      state.files.splice(index, 1);
      renderFiles();
    });
    row.append(image, node("span", file.name), remove);
    $("fileList").append(row);
  });
}
function addFiles(files) {
  const next = [...state.files, ...files];
  if (
    next.length > 10 ||
    next.reduce((sum, f) => sum + f.size, 0) > 20 * 1024 * 1024
  ) {
    notice("Можно добавить до 10 фотографий общим размером до 20 МБ.", true);
    return;
  }
  if (
    next.some(
      (f) =>
        !["image/png", "image/jpeg"].includes(f.type) ||
        f.size > 15 * 1024 * 1024,
    )
  ) {
    notice("Выберите PNG или JPEG. Одна фотография — до 15 МБ.", true);
    return;
  }
  state.files = next;
  notice("");
  renderFiles();
}
async function refreshStatus() {
  try {
    state.status = await request("/api/status");
    const ai = state.status.ai_ready;
    $("recognizeBtn").disabled = !ai;
    $("aiCaption").textContent = ai
      ? "Распознаем задания и подготовим ответы для проверки."
      : "ИИ пока не подключён. Можно работать с примером.";
    $("statusTitle").textContent = state.status.latex_ready
      ? "Печать доступна"
      : "PDF ещё не настроен";
    $("statusText").textContent = ai
      ? "Задания можно распознать по фото."
      : "Готовые примеры доступны без GigaChat.";
    $("statusDot").classList.toggle("ready", state.status.latex_ready);
  } catch (e) {
    notice(e.message, true);
    $("recognizeBtn").disabled = true;
    $("aiCaption").textContent = "Сервер недоступен.";
  }
}
async function prepareMax() {
  const params = new URLSearchParams(location.hash.slice(1));
  let raw = params.get("WebAppData");
  const fromMax = !!raw || params.get("ListokMax") === "1";
  if (params.getAll("WebAppData").length > 1)
    throw new Error(
      "Некорректный запуск. Откройте приложение заново через MAX.",
    );
  if (fromMax && !window.WebApp) {
    await new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "https://st.max.ru/js/max-web-app.js";
      script.onload = resolve;
      script.onerror = () =>
        reject(
          new Error(
            "Не удалось подключиться к MAX. Попробуйте открыть приложение заново.",
          ),
        );
      document.head.append(script);
    });
  }
  raw = window.WebApp?.initData || raw;
  if (raw) {
    state.auth = await request("/api/v2/auth/max", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: raw }),
    });
    params.delete("WebAppData");
    params.set("ListokMax", "1");
    history.replaceState(
      null,
      "",
      location.pathname + location.search + "#" + params.toString(),
    );
  } else {
    state.auth = await request("/api/v2/auth/me");
    if (!state.auth.authenticated && state.auth.local_available)
      state.auth = await request("/api/v2/auth/local", { method: "POST" });
  }
  window.WebApp?.BackButton?.onClick(() => {
    if (state.view === "library" && !$("libraryDetail").hidden) backToLibrary();
    else if (state.view === "publish") showView("saved");
    else if (state.view !== "workspace") showView("workspace");
    else if (state.step > 1) {
      if (state.step === 3) readSettings();
      step(state.step - 1);
    }
  });
  renderAccount();
  if (state.auth.authenticated) {
    await refreshMaterials();
    await pollJobs();
  }
}
function renderAccount() {
  const loggedIn = !!state.auth?.authenticated;
  $("loginPanel").hidden = loggedIn;
  $("workspace").hidden = !loggedIn;
  $("savedView").hidden = true;
  $("libraryView").hidden = true;
  $("publishView").hidden = true;
  $("createNav").disabled = !loggedIn;
  $("savedNav").disabled = !loggedIn;
  $("libraryNav").disabled = !loggedIn;
  $("localLoginBtn").hidden = !state.auth?.local_available;
  $("maxLoginLink").hidden = !state.auth?.max_url;
  if (state.auth?.max_url) $("maxLoginLink").href = state.auth.max_url;
  const local = state.auth?.user?.kind === "local";
  $("accountName").textContent = loggedIn
    ? local
      ? "Локальная проверка"
      : (state.auth.user.first_name || "Профиль") + " · MAX"
    : "ЛатехТим";
  $("logoutBtn").hidden = !loggedIn || local;
}
$("fileInput").addEventListener("change", (e) => {
  addFiles([...e.target.files]);
  e.target.value = "";
});
for (const event of ["dragenter", "dragover"])
  $("dropZone").addEventListener(event, (e) => {
    e.preventDefault();
    $("dropZone").classList.add("dragging");
  });
for (const event of ["dragleave", "drop"])
  $("dropZone").addEventListener(event, (e) => {
    e.preventDefault();
    $("dropZone").classList.remove("dragging");
  });
$("dropZone").addEventListener("drop", (e) =>
  addFiles([...e.dataTransfer.files]),
);
$("demoBtn").addEventListener("click", () =>
  busy("Открываем пример", async () => {
    const result = await request("/api/v2/demo?subject=" + subject());
    loadSheet(result.worksheet, result.source);
  }),
);
$("recognizeBtn").addEventListener("click", () =>
  busy("Передаём задания в обработку", async () => {
    const form = new FormData();
    state.files.forEach((file) => form.append("files", file));
    form.append("subject", subject());
    form.append("text", $("sourceText").value);
    await enqueueJob("recognize", form, false);
  }),
);
$("titleInput").addEventListener("input", () => {
  state.sheet.title = $("titleInput").value;
  invalidate();
});
$("addTaskBtn").addEventListener("click", () => {
  state.sheet.tasks.push({
    id: crypto.randomUUID(),
    question: "",
    answer: "",
    note: "",
  });
  invalidate();
  renderTasks();
  $("taskList").lastElementChild.querySelector("textarea").focus();
});
$("backToInput").addEventListener("click", () => {
  notice("");
  step(1);
});
$("toSettings").addEventListener("click", () => {
  if (validTasks()) {
    notice("");
    renderSettings();
    step(3);
  }
});
$("backToTasks").addEventListener("click", () => {
  readSettings();
  step(2);
});
for (const id of ["teacherInput", "gradeInput", "columnsSelect", "countSelect"])
  $(id).addEventListener("change", () => {
    invalidate();
    readSettings();
    summary();
  });
document.querySelectorAll('[name="field"]').forEach((n) =>
  n.addEventListener("change", () => {
    invalidate();
    readSettings();
  }),
);
$("reviewCheckbox").addEventListener("change", () => {
  $("compileBtn").disabled =
    !$("reviewCheckbox").checked || !state.status?.latex_ready;
});
$("compileBtn").addEventListener("click", () =>
  busy("Сохраняем лист и ставим на сборку", async () => {
    readSettings();
    if (state.dirty || !state.savedId) await saveCurrent();
    await enqueueJob("compile", {
      worksheet: state.sheet,
      material_id: state.savedId,
      revision: state.revision,
      reviewed: $("reviewCheckbox").checked,
    });
  }),
);
$("editAgain").addEventListener("click", () => {
  notice("");
  step(2);
});
for (const id of ["saveBtn", "saveDraftBtn", "saveCopyBtn"]) {
  $(id).addEventListener("click", () =>
    busy("Сохраняем в ваш профиль", async () => {
      await saveCurrent(id === "saveCopyBtn");
      notice("Лист сохранён в «Моих материалах».");
    }),
  );
}
document.querySelectorAll("[data-variant]").forEach((button) =>
  button.addEventListener("click", () =>
    busy("Сохраняем лист и заказываем вариант", async () => {
      if (state.dirty || !state.savedId) await saveCurrent();
      await enqueueJob("variant", {
        worksheet: state.sheet,
        material_id: state.savedId,
        revision: state.revision,
        difficulty: button.dataset.variant,
      });
    }),
  ),
);
$("createNav").addEventListener("click", () => showView("workspace"));
$("savedNav").addEventListener("click", () => showView("saved"));
$("libraryNav").addEventListener("click", () => showView("library"));
$("shareFromSaved").addEventListener("click", () => {
  showView("saved");
  notice("Нажмите «Поделиться» у листа, который хотите опубликовать.");
});
$("libraryBack").addEventListener("click", backToLibrary);
$("cancelPublish").addEventListener("click", () => showView("saved"));
$("librarySearchForm").addEventListener("submit", (event) => {
  event.preventDefault();
  busy("Ищем материалы", () => refreshLibrary());
});
for (const id of ["librarySubject", "librarySort"])
  $(id).addEventListener("change", () =>
    busy("Обновляем библиотеку", () => refreshLibrary()),
  );
$("libraryMore").addEventListener("click", () =>
  busy("Загружаем материалы", () => refreshLibrary(true)),
);
$("publishForm").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!state.publishDraft) return;
  busy("Публикуем лист", async () => {
    const draft = state.publishDraft;
    const result = await request("/api/v2/materials/" + draft.id + "/publish", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        revision: draft.revision,
        author: $("publishAuthor").value.trim(),
        description: $("publishDescription").value.trim(),
        reviewed: $("publishReviewed").checked,
      }),
    });
    state.publishDraft = null;
    await refreshMaterials();
    renderPublication(result.publication);
    notice(
      "Лист появился в библиотеке. Правки личного черновика не меняют публикацию.",
    );
  });
});
$("copyPublication").addEventListener("click", () => {
  if (
    state.dirty &&
    !window.confirm(
      "Открыть копию из библиотеки? Несохранённые изменения текущего листа будут потеряны.",
    )
  )
    return;
  busy("Сохраняем основу в ваш профиль", async () => {
    const { material } = await request(
      "/api/v2/library/" + state.publication.id + "/copy",
      { method: "POST" },
    );
    loadSheet(
      material.worksheet,
      material.source,
      material.id,
      material.origin,
    );
    state.revision = material.revision;
    await refreshMaterials();
    notice(
      "Копия сохранена в «Моих материалах». Теперь можно изменить её под свой класс.",
    );
  });
});
$("withdrawPublication").addEventListener("click", () => {
  $("withdrawConfirm").hidden = false;
  $("withdrawPublication").setAttribute("aria-expanded", "true");
  $("confirmWithdraw").focus();
});
$("cancelWithdraw").addEventListener("click", () => {
  $("withdrawConfirm").hidden = true;
  $("withdrawPublication").setAttribute("aria-expanded", "false");
  $("withdrawPublication").focus();
});
$("confirmWithdraw").addEventListener("click", () => {
  busy("Снимаем публикацию", async () => {
    await request("/api/v2/library/" + state.publication.id, {
      method: "DELETE",
    });
    state.publication = null;
    await refreshMaterials();
    await refreshLibrary();
    showLibraryList();
    notice("Лист снят с публикации. Личный материал сохранён.");
  });
});
$("newSheetBtn").addEventListener("click", () => {
  if (
    state.dirty &&
    !window.confirm(
      "Начать новый лист? Несохранённые изменения будут потеряны.",
    )
  )
    return;
  state.sheet = null;
  state.savedId = null;
  state.revision = null;
  state.result = null;
  state.files = [];
  renderFiles();
  $("sourceText").value = "";
  markDirty(false);
  showView("workspace");
  notice("");
  step(1);
});
$("materialSearch").addEventListener("input", renderSaved);
$("materialSort").addEventListener("change", renderSaved);
$("localLoginBtn").addEventListener("click", () =>
  busy("Открываем профиль", prepareMax),
);
$("logoutBtn").addEventListener("click", () => {
  if (state.dirty && !window.confirm("Выйти без сохранения изменений?")) return;
  busy("Выходим из профиля", async () => {
    await request("/api/v2/auth/logout", { method: "POST" });
    markDirty(false);
    location.reload();
  });
});
$("importLocalBtn").addEventListener("click", () => {
  if (
    !window.confirm(
      "Перенести старые листы из этого браузера в текущий профиль?",
    )
  )
    return;
  busy("Переносим материалы", async () => {
    for (const item of saved()) {
      await request("/api/v2/materials", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          worksheet: item.worksheet,
          source: "browser_import",
        }),
      });
      localStorage.setItem(
        storageKey,
        JSON.stringify(saved().filter((other) => other.id !== item.id)),
      );
    }
    await refreshMaterials();
    notice("Материалы перенесены в профиль.");
  });
});
window.addEventListener("beforeunload", (e) => {
  if (state.dirty) {
    e.preventDefault();
    e.returnValue = "";
  }
});
$("workspace").hidden = true;
$("createNav").disabled = true;
$("savedNav").disabled = true;
$("libraryNav").disabled = true;
updateCount();
refreshStatus();
busy("Открываем ваш профиль", async () => {
  try {
    await prepareMax();
  } catch (error) {
    renderAccount();
    throw error;
  }
});

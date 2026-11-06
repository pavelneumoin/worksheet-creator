"use strict";

function rosterNames(text) {
  return text.split(/\r?\n/).map(s => s.trim().replace(/^\d+[.)]\s*/, "")).filter(Boolean);
}
function rosterCsv(mapping) {
  const cell = value => '"' + (/^[\s]*[=+@\-\t\r]/.test(value) ? "'" : "") + value.replaceAll('"', '""') + '"';
  return "\uFEFF" + [["Код ученика", "ФИО"], ...mapping].map(row => row.map(cell).join(";")).join("\r\n");
}
function rosterMapping(students, names) {
  if (students.length !== names.length || new Set(students.map(s => s.code)).size !== names.length)
    throw new Error("Не удалось сопоставить все строки. Повторите тот же запрос; новые коды не создадутся.");
  return students.map((student, index) => [student.code, names[index]]);
}
function downloadRoster(mapping, className) {
  const url = URL.createObjectURL(new Blob([rosterCsv(mapping)], {type:"text/csv;charset=utf-8"}));
  const link = node("a");
  link.href = url; link.download = "Ученики — " + className.replace(/[<>:\"/\\|?*]/g, "_") + ".csv";
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}

async function openRosterResult(job) {
  const recognized = await request("/api/v2/jobs/" + job.id + "/roster");
  await openClass(recognized.class_id, "students");
  const target = $("classDetail");
  target.querySelector(".roster-import")?.remove();
  renderLocalRosterImport(target, classState.current, recognized, job.id);
  target.querySelector(".roster-import").scrollIntoView({behavior:"smooth",block:"start"});
}

async function showReadyRoster(jobs) {
  const box = document.querySelector('.roster-import[data-job-id]');
  if (!box || box.closest('[hidden]') || box.dataset.opening) return;
  const job = jobs.find(item => item.id === box.dataset.jobId);
  if (!job) return;
  if (['failed', 'cancelled'].includes(job.status)) {
    box.removeAttribute('data-job-id');
    box.querySelector('form').hidden = false;
    notice(job.error || 'Распознавание отменено. Можно вставить список вручную.', true); return;
  }
  if (job.status !== 'succeeded') return;
  box.dataset.opening = 'true';
  try { await openRosterResult(job); }
  catch (error) { box.removeAttribute('data-job-id'); notice(error.message, true); }
}

function renderLocalRosterImport(target, classroom, recognized = null, jobId = null) {
  const box = node("details", undefined, "panel roster-import");
  box.open = !!recognized;
  box.append(node("summary", "Добавить учеников по фото или списку"));
  const photo = node("div", undefined, "roster-photo");
  const photoLabel = node("label", "Фото списка учеников"), files = node("input");
  files.type = "file"; files.accept = "image/jpeg,image/png"; files.multiple = true;
  photoLabel.append(files);
  const photoInfo = node("p", "До 3 фото PNG/JPEG · до 100 учеников · до 15 МБ на фото и 20 МБ всего. Снимите только столбец с именами.", "quiet");
  const privacy = node("p", "Фото обрабатывает внешний сервис распознавания. На нашем сервере фото удаляются после обработки, временный список — после создания кодов или через 15 минут. В базе учеников сохраняются только коды.", "quiet");
  const recognize = classButton("Распознать список", async () => {
    const selected = Array.from(files.files);
    if (!selected.length || selected.length > 3 || selected.some(f => f.size > 15 * 1024 * 1024) || selected.reduce((s,f) => s+f.size, 0) > 20 * 1024 * 1024)
      return notice("Выберите от 1 до 3 фото: до 15 МБ каждое, всего до 20 МБ.", true);
    recognize.disabled = true;
    await busy("Отправляем фото списка", async () => {
      const body = new FormData();
      body.append("class_id", classroom.id); body.append("consent", "true");
      selected.forEach(file => body.append("files", file));
      const job = await enqueueJob("roster_recognize", body, false);
      box.dataset.jobId = job.id;
      form.hidden = true;
      photoInfo.textContent = "Список распознаётся. Когда он будет готов, здесь появятся имена для проверки. Можно вернуться позже через блок «Задачи».";
      files.value = "";
    });
    recognize.disabled = false;
  }, "secondary");
  photo.append(photoLabel, photoInfo, privacy, recognize);
  const form = node("form"), label = node("label", recognized ? "Проверьте имена и порядок строк" : "Или вставьте список: один ученик на строку");
  const input = node("textarea"); input.rows = 7; input.maxLength = 12000; input.autocomplete = "off";
  input.placeholder = "Иванов Иван\nПетрова Анна"; label.append(input);
  const hint = node("p", "При создании кодов отправляется только количество учеников. Таблица «имя → код» скачивается на ваше устройство; сохраните её до ухода со страницы.", "quiet");
  const warnings = node("p", undefined, "review-warning"), preview = node("p", undefined, "quiet");
  if (recognized) {
    input.value = recognized.rows.map((row,i) => row.name || "[неразборчиво: строка "+(i+1)+"]").join("\n");
    const uncertain = recognized.rows.flatMap((row,i) => row.uncertain ? [i+1] : []);
    warnings.textContent = uncertain.length ? "Сверьте с фото строки: "+uncertain.join(", ")+". Замените неразборчивые строки вручную; ничего не удалялось автоматически." : "Сверьте список с фото: ИИ может ошибиться в буквах или пропустить строку.";
    photo.hidden = true;
  }
  const reviewLabel = node("label", undefined, "roster-confirm"), reviewed = node("input");
  reviewed.type = "checkbox"; reviewed.required = true;
  reviewLabel.append(reviewed, node("span", "Я проверил имена, порядок и количество учеников"));
  const result = node("div", undefined, "roster-result"), submit = node("button", "Создать коды и скачать таблицу", "button primary");
  submit.type = "submit";
  let mapping = null, pending = null;
  function updateCount() {
    const rows = rosterNames(input.value), repeats = rows.length - new Set(rows.map(s => s.toLocaleLowerCase())).size;
    preview.textContent = "В списке: "+rows.length+". В классе уже есть: "+classroom.student_count+". Создадим новые коды." + (repeats ? " Повторяющихся имён: "+repeats+" — проверьте; однофамильцы не объединяются." : "");
  }
  input.addEventListener("input", () => { reviewed.checked = false; updateCount(); }); updateCount();
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const rows = pending?.names || rosterNames(input.value);
    if (!rows.length || rows.length > 100 || rows.some(s => s.length > 120 || /[\x00-\x1f]|\[неразборчиво:/i.test(s)))
      return notice("Нужно от 1 до 100 заполненных строк, до 120 символов. Исправьте неразборчивые имена.", true);
    if (!reviewed.checked) return notice("Сначала проверьте список учеников.", true);
    submit.disabled = true; input.disabled = true; reviewed.disabled = true;
    await busy("Создаём постоянные коды", async () => {
      if (!pending) {
        const fresh = (await request("/api/v2/classes/"+classroom.id)).classroom;
        pending = {names: rows, body: {request_key: jobId || crypto.randomUUID(), revision: fresh.revision, count: rows.length}};
      }
      let response;
      try { response = await request("/api/v2/classes/"+classroom.id+"/roster-imports", classJson("POST", pending.body)); }
      catch (error) {
        if (error.status && error.status < 500) pending = null;
        else notice("Ответ сервера не получен. Повторите эту кнопку — список защищён от дубликатов.", true);
        throw error;
      }
      mapping = rosterMapping(response.students, pending.names);
      classState.current = response.classroom;
      const countLabel = target.querySelector(".class-heading .quiet");
      if (countLabel) countLabel.textContent = "Учеников: "+response.classroom.student_count+" · Активных работ: "+response.classroom.assignment_count;
      const download = classButton("Скачать таблицу ещё раз", () => downloadRoster(mapping, classroom.name), "primary");
      const saved = classButton("Таблица сохранена — открыть класс", () => busy("Открываем класс", () => openClass(classroom.id, "students")));
      result.replaceChildren(node("p", "Кодов создано: "+mapping.length+". Скачивание CSV начато. Если браузер его остановил, нажмите «Скачать таблицу ещё раз»."), download, saved);
      label.hidden = hint.hidden = preview.hidden = warnings.hidden = reviewLabel.hidden = submit.hidden = photo.hidden = true;
      input.value = ""; pending = null;
      downloadRoster(mapping, classroom.name);
      if (jobId) {
        try {
          await request("/api/v2/jobs/"+jobId+"/roster", {method:"DELETE"});
          await request("/api/v2/jobs/"+jobId+"/acknowledge", {method:"POST"});
          await refreshJobs();
        } catch { result.append(node("p", "Временный список будет удалён автоматически по сроку хранения.", "quiet")); }
      }
    });
    if (!mapping) {
      submit.disabled = false; input.disabled = !!pending; reviewed.disabled = !!pending;
      submit.textContent = pending ? "Повторить запрос и скачать таблицу" : "Создать коды и скачать таблицу";
    }
  });
  form.append(label, hint, warnings, preview, reviewLabel, submit, result);
  box.append(photo, form); target.append(box);
}

if (typeof module !== "undefined") module.exports = {rosterNames, rosterCsv, rosterMapping};

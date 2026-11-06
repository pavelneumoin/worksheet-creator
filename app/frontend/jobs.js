"use strict";
// Long tasks live on the server. Only the short submission uses the busy overlay.
let jobTimer;
let jobRefresh;
let jobSnapshot = "";
let pendingSubmission = null;
let currentJobs = [];

function jobButton(text, action, cls = "secondary") {
  const button = node("button", text, "button " + cls);
  button.addEventListener("click", () => busy(text, action));
  return button;
}

function renderJobs() {
  let tray=$("activityTray");
  if(!tray){tray=node("section",undefined,"activity-tray");tray.id="activityTray";tray.setAttribute("aria-label","Текущая обработка и результат");$("jobsPanel").before(tray);}
  tray.replaceChildren();
  const active = currentJobs.find((job) =>
    ["queued", "running"].includes(job.status),
  );
  const done = currentJobs.filter((job) => job.status === "succeeded").length;
  $("jobsPanel").hidden = !currentJobs.length && !pendingSubmission;
  $("jobsSummary").textContent = active
    ? active.status === "running"
      ? "в работе"
      : "в очереди"
    : done
      ? done + " готово"
      : currentJobs.some(j => j.status === "failed") ? "Требует внимания" : "";
  $("submissionRetry").hidden = !pendingSubmission;
  $("retrySubmission").onclick = () =>
    busy("Повторяем отправку", sendPendingJob);
  $("jobsList").replaceChildren();
  const featured=active||currentJobs.find(j=>j.status==="succeeded")||currentJobs[0];
  for (const job of currentJobs.slice(0, 8)) {
    const card = node("article", undefined, "job-card job-" + job.status);
    const labels = {recognize:"Распознавание заданий",variant:"Новый вариант",compile:"Рабочий лист PDF",grade:"Проверка ответов",batch_grade:"Проверка PDF",roster_recognize:"Список учеников",answer_forms:"Бланки ответов",analytics_pdf:"Отчёт PDF",report_pdf:"Отчёт по работе",analytics_insight:"Рекомендации"};
    const heading = node("h3", job.result?.worksheet?.title || labels[job.kind] || job.label);
    const info = node("div", undefined, "job-info");
    const status =
      job.status === "queued"
        ? "В очереди · место " + job.position
        : job.status === "running"
          ? "Выполняется"
          : job.status === "succeeded"
            ? job.kind === "roster_recognize" ? "Список готов · откройте в течение 15 минут" : "Готово и сохранено"
            : job.status === "cancelled"
              ? "Отменено до начала обработки"
              : job.error || "Обработка не завершилась. Повторите действие.";
    info.append(
      heading,
      node("p", status, job.status === "failed" ? "job-error" : "quiet"),
    );
    if (job.result?.warning)
      info.append(node("p", job.result.warning, "job-error"));
    const actions = node("div", undefined, "actions");
    if (job.status === "succeeded" && job.result?.materials?.length > 1) {
      for (const material of job.result.materials)
        actions.append(
          jobButton("Вариант " + material.variant, () =>
            openJobResult(job, material.material_id),
          ),
        );
    } else if (job.status === "succeeded")
      actions.append(
        jobButton("Открыть", () => openJobResult(job), "primary"),
      );
    if(job.status==="succeeded"&&job.kind==="compile"&&job.result?.pdf_url){
      for(const [label,key,name] of [["Скачать PDF","pdf_url","Рабочий лист.pdf"],["Ответы","keys_url","Ответы.pdf"],["Бланк ответов","answer_form_url","Бланк ответов.pdf"]]){
        if(!job.result[key])continue;
        const link=node("a",label,"button secondary");link.href=job.result[key];link.target="_blank";link.rel="noopener";link.download=name;
        bindArtifactDownload(link,job.result.artifact_id,key,name);actions.append(link);
      }
      if(job.result.material_id)actions.append(jobButton("Назначить классу",()=>openAssignmentForm(null,job.result.material_id)));
    }
    if (job.status === "queued")
      actions.append(
        jobButton(
          "Отменить",
          async () => {
            await request("/api/v2/jobs/" + job.id + "/cancel", {
              method: "POST",
            });
            await refreshJobs();
          },
          "ghost",
        ),
      );
    if (!["queued", "running"].includes(job.status))
      actions.append(
        jobButton(
          "Скрыть",
          async () => {
            await request("/api/v2/jobs/" + job.id + "/acknowledge", {
              method: "POST",
            });
            await refreshJobs();
          },
          "ghost",
        ),
      );
    card.append(info, actions);
    if(job.id===featured?.id)tray.append(card);else $("jobsList").append(card);
  }
  tray.hidden=!tray.childElementCount;
  $("jobsPanel").hidden=!$("jobsList").childElementCount&&!pendingSubmission;
  if (currentJobs.length > 8)
    $("jobsList").append(
      node(
        "p",
        "Показаны последние 8 задач. Листы доступны в материалах, проверки и отчёты - в классах.",
        "quiet",
      ),
    );
}

async function refreshJobs() {
  if (!state.auth?.authenticated) return;
  if (jobRefresh) return jobRefresh;
  jobRefresh = (async () => {
    const data = await request("/api/v2/jobs");
    currentJobs = data.jobs;
    if (
      pendingSubmission &&
      currentJobs.some((job) => job.request_key === pendingSubmission.key)
    )
      pendingSubmission = null;
    const snapshot = JSON.stringify([currentJobs, !!pendingSubmission]);
    if (snapshot !== jobSnapshot) {
      const firstLoad = !jobSnapshot;
      const justCompleted = currentJobs.some(
        (job) => job.status === "succeeded",
      );
      jobSnapshot = snapshot;
      renderJobs();
      if (firstLoad)
        $("jobsPanel").open = false;
      if (justCompleted) await refreshMaterials();
    }
    $("jobsConnection").hidden = true;
    if (typeof showReadyRoster === "function") await showReadyRoster(currentJobs);
  })();
  try {
    await jobRefresh;
  } finally {
    jobRefresh = null;
  }
}

async function pollJobs() {
  clearTimeout(jobTimer);
  try {
    await refreshJobs();
  } catch {
    $("jobsConnection").textContent =
      "Нет связи. Проверим снова автоматически. Принятые сервером задачи продолжаются.";
    $("jobsConnection").hidden = false;
  }
  if (state.auth?.authenticated)
    jobTimer = setTimeout(
      pollJobs,
      document.hidden
        ? 15000
        : currentJobs.some((job) =>
              ["queued", "running"].includes(job.status),
            ) || pendingSubmission
          ? 2500
          : 10000,
    );
}

async function sendPendingJob() {
  if (!pendingSubmission) return;
  const submission = pendingSubmission;
  try {
    const response = await request("/api/v2/jobs/" + submission.kind, {
      method: "POST",
      headers: {
        "Idempotency-Key": submission.key,
        ...(submission.json ? { "Content-Type": "application/json" } : {}),
      },
      body: submission.json ? JSON.stringify(submission.body) : submission.body,
    });
    pendingSubmission = null;
    currentJobs = [
      response.job,
      ...currentJobs.filter((job) => job.id !== response.job.id),
    ];
    renderJobs();
    $("jobsPanel").open = false;
    notice(
      submission.kind === "report_pdf"
        ? "PDF отчёта готовится. Снимок результатов сохранён; файл появится в блоке «Задачи»."
        : submission.kind === "answer_forms"
          ? "Бланки готовятся. Откройте результат в «Задачах»; PDF также сохранится в назначенной работе."
        : submission.kind === "roster_recognize"
          ? "Распознаём список. После завершения откройте результат здесь и проверьте имена."
          : "Задача принята. Результат появится здесь и в ваших материалах.",
    );
    $("activityTray")?.scrollIntoView({ behavior: "smooth", block: "start" });
    pollJobs();
    return response.job;
  } catch (error) {
    // A definite HTTP rejection can be corrected; a lost reply must reuse its key.
    if (error.status && error.status < 500) pendingSubmission = null;
    renderJobs();
    $("jobsPanel").open = true;
    throw error;
  }
}

async function enqueueJob(kind, body, json = true) {
  if (pendingSubmission)
    throw new Error(
      "Сначала повторите отправку предыдущей задачи в блоке «Задачи».",
    );
  pendingSubmission = {
    kind,
    body: json ? structuredClone(body) : body,
    json,
    key: crypto.randomUUID(),
  };
  return await sendPendingJob();
}

async function openJobResult(job, chosenMaterial = null) {
  if(job.kind === "material_form"){const link=node("a","Скачать бланк A4","button primary");link.href=job.result.pdf_url;link.target="_blank";link.rel="noopener";bindArtifactDownload(link,job.result.artifact_id,"pdf_url","Бланк ответов.pdf");$("activityTray").append(link);notice("Бланк готов.");return;}
  if(job.kind === "solution_review") return job.result.target_kind === "student" ? openStudentAttempt(job.result.target_id) : openReview(job.result.target_id);
  if(job.kind === "student_grade") return openStudentAttempt(job.result.student_attempt_id);
  // Preserve any edits made while a task was running.
  if (state.dirty && state.sheet) await saveCurrent();
  const fresh = (await request("/api/v2/jobs/" + job.id)).job;
  if (fresh.status !== "succeeded") throw new Error("Результат ещё не готов.");
  if (fresh.kind === "roster_recognize") {
    await openRosterResult(fresh); return;
  }
  if (fresh.kind === "answer_forms") {
    showView("classes", false);
    await openAssignment(fresh.result.assignment_id);
    notice("Бланки готовы. Скачайте PDF в разделе «Быстрая проверка по ответам».");
    return;
  }
  if (["analytics_pdf","analytics_insight"].includes(fresh.kind)) {
    await openAnalytics(fresh.result.filters);
    if(fresh.kind==="analytics_insight")showAnalyticsInsight(fresh.result);
    else showAnalyticsDownload(fresh.result);
    return;
  }
  if (fresh.kind === "batch_grade") {
    await openBatch(fresh.result.batch_id);
    await request("/api/v2/jobs/"+job.id+"/acknowledge",{method:"POST"});
    await refreshJobs();return;
  }
  if (fresh.kind === "report_pdf") {
    await openClassReport(fresh.result.assignment_id);
    showReportDownload(fresh.result);
    return;
  }
  if (fresh.kind === "grade") {
    await openReview(fresh.result.review_id);
    await request("/api/v2/jobs/" + job.id + "/acknowledge", {
      method: "POST",
    });
    await refreshJobs();
    return;
  }
  const result = { ...fresh.result };
  if (
    chosenMaterial &&
    result.materials?.some((m) => m.material_id === chosenMaterial)
  )
    result.material_id = chosenMaterial;
  if (result.material_id) {
    const material = (await request("/api/v2/materials/" + result.material_id))
      .material;
    if (
      result.artifact_id &&
      material.result?.artifact_id !== result.artifact_id
    ) {
      loadSheet(result.worksheet, result.source, null, material.origin);
      state.result = result;
      notice(
        "После сборки исходный лист изменился. Открыта готовая версия из этой задачи — её можно сохранить отдельно.",
      );
    } else {
      loadSheet(
        material.worksheet,
        material.source,
        material.id,
        material.origin,
      );
      state.revision = material.revision;
      state.result = material.result;
    }
  } else {
    loadSheet(result.worksheet, result.source);
    state.result = result;
    notice(
      "Исходный лист изменился во время сборки. Здесь готова отдельная версия — её можно сохранить как новый материал.",
    );
  }
  if (state.result) {
    await renderResult();
    step(4);
  } else notice("Черновик сохранён. Проверьте условия и ответы перед печатью.");
  if (result.warning) notice(result.warning);
  if (!result.materials || result.materials.length === 1)
    await request("/api/v2/jobs/" + job.id + "/acknowledge", {
      method: "POST",
    });
  await refreshJobs();
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) pollJobs();
});
window.addEventListener("online", pollJobs);

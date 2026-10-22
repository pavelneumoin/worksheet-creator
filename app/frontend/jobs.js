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
      ? "готово: " + done
      : "";
  $("submissionRetry").hidden = !pendingSubmission;
  $("retrySubmission").onclick = () =>
    busy("Повторяем отправку", sendPendingJob);
  $("jobsList").replaceChildren();
  for (const job of currentJobs.slice(0, 8)) {
    const card = node("article", undefined, "job-card");
    const heading = node("h3", job.label);
    const status =
      job.status === "queued"
        ? "В очереди · место " + job.position
        : job.status === "running"
          ? "Выполняется. Можно продолжить работу с другими материалами."
          : job.status === "succeeded"
            ? "Готово и сохранено"
            : job.status === "cancelled"
              ? "Отменено до начала обработки"
              : job.error || "Обработка не завершилась. Повторите действие.";
    card.append(
      heading,
      node("p", status, job.status === "failed" ? "job-error" : "quiet"),
    );
    if (job.result?.warning)
      card.append(node("p", job.result.warning, "job-error"));
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
        jobButton("Открыть результат", () => openJobResult(job), "primary"),
      );
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
          "Убрать из списка",
          async () => {
            await request("/api/v2/jobs/" + job.id + "/acknowledge", {
              method: "POST",
            });
            await refreshJobs();
          },
          "ghost",
        ),
      );
    card.append(actions);
    $("jobsList").append(card);
  }
  if (currentJobs.length > 8)
    $("jobsList").append(
      node(
        "p",
        "Показаны последние 8 задач. Готовые листы доступны в «Моих материалах».",
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
        $("jobsPanel").open = currentJobs.some((job) =>
          ["queued", "running"].includes(job.status),
        );
      if (justCompleted) await refreshMaterials();
    }
    $("jobsConnection").hidden = true;
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
    $("jobsPanel").open = true;
    notice("Задача принята. Результат появится здесь и в ваших материалах.");
    $("jobsPanel").scrollIntoView({ behavior: "smooth", block: "start" });
    pollJobs();
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
  await sendPendingJob();
}

async function openJobResult(job, chosenMaterial = null) {
  // Preserve any edits made while a task was running.
  if (state.dirty && state.sheet) await saveCurrent();
  const fresh = (await request("/api/v2/jobs/" + job.id)).job;
  if (fresh.status !== "succeeded") throw new Error("Результат ещё не готов.");
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

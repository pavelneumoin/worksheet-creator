"use strict";
let demoManifest = null;
function renderDemoAccess() {
  $("demoEnter").hidden = !state.auth?.authenticated || !!state.auth?.demo;
  $("demoBar").hidden = !state.auth?.demo;
}
async function switchDemo(path) {
  if (typeof flushStudentDraft === "function") await flushStudentDraft();
  if (typeof flushReviewDraft === "function") await flushReviewDraft();
  if (state.dirty && state.sheet) await saveCurrent();
  if (pendingSubmission) throw new Error("Сначала завершите отправку задачи.");
  await request("/api/v2/demo-space/" + path, {method:"POST"});
  state.dirty = false;
  if (typeof resetReviewEditor === "function") resetReviewEditor();
  if (typeof resetStudentEditor === "function") resetStudentEditor();
  location.assign("/");
}
async function enterDemo() {
  if (state.auth?.demo) {
    const url = new URL(location.href);url.searchParams.delete("open");history.replaceState(null,"",url.pathname+url.search);
    await loadDemoGuide();$("demoGuide").open=true;return;
  }
  await switchDemo("enter");
}
async function demoOpenMaterial(id) {
  if(state.dirty && state.sheet)await saveCurrent();
  const material=(await request("/api/v2/materials/"+id)).material;
  loadSheet(material.worksheet,material.source,material.id,material.origin);
  state.revision=material.revision;state.result=material.result;
  if(state.result){await renderResult();step(4);}else step(2);
}
async function loadDemoGuide() {
  demoManifest=(await request("/api/v2/demo-space")).demo;
  const d=demoManifest, steps=$("demoSteps");steps.replaceChildren();
  const actions=[
    ["01","Рабочий лист","Задания, оформление и PDF",()=>demoOpenMaterial(d.materials.trigonometry||d.materials.fractions)],
    ["02","Класс и ученики","Коды и назначенные работы",()=>openClass(d.classes[0])],
    ["03","Проверка ответа","Скан и частичные баллы",()=>openReview(d.review)],
    ["04","Пачка сканов","Готовая страница с QR",()=>openBatch(d.batch)],
    ["05","Загрузить PDF","Работа для пробной проверки",()=>openBatchHome(d.upload_assignment,d.classes[0])],
    ["06","Статистика школы","Результаты по классам и темам",()=>openAnalytics({scope:"school"})],
    ["07","От учеников","Исправление и повторная сдача",()=>openStudentAttempt(d.student_attempt)],
    ["08","Кабинет ученика","Свои работы, баллы и исправления",()=>openStudentHome()],
  ];
  for(const [n,title,caption,action] of actions){const button=node("button",undefined,"demo-step");button.type="button";const body=node("span");body.append(node("strong",title),node("small",caption));button.append(node("b",n),body,node("span","↗","demo-arrow"));button.addEventListener("click",()=>busy("Открываем пример",async()=>{await action();$("demoGuide").open=false;}));steps.append(button);}
  const link=$("demoScanDownload");link.href=d.sample_pdf.pdf_url;link.target="_blank";link.rel="noopener";
  bindArtifactDownload(link,d.sample_pdf.artifact_id,"pdf_url","ЛистОК — учебные ответы.pdf");
  $("demoGuide").open=true;
  renderDemoAccess();
}
$("demoEnter").addEventListener("click",()=>busy("Готовим демо-кабинет",enterDemo));
$("demoExit").addEventListener("click",()=>busy("Возвращаемся в кабинет",()=>switchDemo("exit")));

"use strict";
// Small, progressively enhanced controls on top of the existing editor.
const studioTemplates = [
  ["cards", "Карточки", "Каждому заданию — своё место"],
  ["list", "Лаконичный", "Только главное, без рамок"],
  ["guided", "По шагам", "Дано, решение и ответ"],
  ["check", "С проверкой", "Место для обратной связи"],
];
function studioIcon(path) {
  return listokPathIcon(path);
}
const studioNavIcons={createNav:"filePlus",savedNav:"library",libraryNav:"sharedLibrary",classesNav:"classes",scheduleNav:"calendar"};
for(const [id,name] of Object.entries(studioNavIcons)) $(id)?.prepend(listokIcon(name));
const studioBrandCaption=node("div","Рабочее пространство учителя","brand-caption");
document.querySelector(".brand").after(studioBrandCaption);

function addHeightControl(selectId, anchor) {
  const label=node("label", "Высота поля для решения", "field-label height-control");
  const select=node("select"); select.id=selectId;
  for(const [value,text] of [[0,"По макету"],[10,"1 см"],[20,"2 см"],[30,"3 см"],[40,"4 см"],[50,"5 см"],[70,"7 см"],[100,"10 см"]]) {const option=node("option",text);option.value=value;select.append(option);}
  label.append(select); anchor.after(label);
  select.addEventListener("change",()=>{if(selectId==="fieldHeight"&&state.sheet){invalidate();readSettings();summary();} renderStudioPreview();});
}
addHeightControl("setupHeight",$("setupCount").closest(".form-grid"));
addHeightControl("fieldHeight",$("countSelect").closest(".form-grid"));

function templatePicker(select) {
  const grid=node("div",undefined,"template-picker"); grid.setAttribute("role","group");grid.setAttribute("aria-label","Шаблоны рабочего листа");
  for(const [value,title,description] of studioTemplates) {
    const button=node("button",undefined,"template-choice");button.type="button";button.dataset.template=value;
    const thumb=node("span",undefined,"template-thumb template-"+value);
    for(let i=0;i<3;i++)thumb.append(node("i"));
    button.append(thumb,node("strong",title),node("small",description));
    button.addEventListener("click",()=>{select.value=value;select.dispatchEvent(new Event("change",{bubbles:true}));sync();});grid.append(button);
  }
  const sync=()=>{for(const button of grid.children)button.setAttribute("aria-pressed",String(button.dataset.template===select.value));renderStudioPreview();};
  select.closest("label").before(grid);select.addEventListener("change",sync);sync();
}

const studioPreview=node("section",undefined,"studio-preview");
studioPreview.setAttribute("aria-label","Схема выбранного макета");
studioPreview.append(node("h3","Макет листа"));
const studioPaper=node("div",undefined,"studio-paper");studioPaper.setAttribute("aria-hidden","true");
const studioPreviewCaption=node("p",undefined,"preview-caption");
const studioPreviewWarning=node("p",undefined,"preview-warning");studioPreviewWarning.setAttribute("role","status");
studioPreview.append(studioPaper,studioPreviewCaption,studioPreviewWarning,node("p","Схема макета. Точный вид — в готовом PDF.","quiet"));
document.querySelector(".sidebar").prepend(studioPreview);

function renderStudioPreview() {
  if(!$("setupHeight") || !studioPaper) return;
  const editing=state.step===3;
  const s=editing?{columns:Number($("columnsSelect").value),tasks_per_page:Number($("countSelect").value),field:document.querySelector('[name="field"]:checked').value,template:$("templateSelect").value,field_height_mm:Number($("fieldHeight").value)}:initialSettings();
  studioPaper.replaceChildren();
  const title=node("strong",state.sheet?.title||"Тема вашего урока");
  studioPaper.append(node("span","ЛистОК · рабочий лист","paper-kicker"),title,node("div","Код ученика __________  Дата ______","paper-meta"));
  const cells=node("div",undefined,"paper-cells");cells.style.gridTemplateColumns=`repeat(${s.columns}, minmax(0,1fr))`;
  for(let i=0;i<s.tasks_per_page;i++) {
    const cell=node("div",undefined,"paper-task paper-"+s.template);cell.append(node("b",String(i+1).padStart(2,"0")),node("span",undefined,"paper-line"),node("span",undefined,"paper-line short"));
    if(s.field!=="none") {const field=node("div",undefined,"paper-field paper-field-"+s.field);field.style.height=(s.field_height_mm?Math.min(s.field_height_mm*.7,70):Math.max(12,100/Math.ceil(s.tasks_per_page/s.columns)))+"px";cell.append(field);}
    cells.append(cell);
  }
  studioPaper.append(cells,node("div","Место для открытий и верных решений","paper-footer"));
  studioPreviewCaption.textContent=`A4 · ${s.columns===1?"1 столбец":"2 столбца"} · ${s.tasks_per_page} на странице`;
  const rows=Math.ceil(s.tasks_per_page/s.columns);
  studioPreviewWarning.textContent=s.field!=="none"&&s.field_height_mm*rows>170?"Большое поле: уменьшите число заданий на странице, если сборка сообщит о переполнении.":"";
  studioPreviewWarning.hidden=!studioPreviewWarning.textContent;
  for(const id of ["setupHeight","fieldHeight"])$(id).disabled=(id==="setupHeight"?$("setupField").value:document.querySelector('[name="field"]:checked').value)==="none";
  for(const picker of document.querySelectorAll(".template-picker")) {
    const selected=picker.closest("#step3")?$("templateSelect").value:$("setupTemplate").value;
    for(const btn of picker.children)btn.setAttribute("aria-pressed",String(btn.dataset.template===selected));
  }
  document.dispatchEvent(new Event("listok:settingschange"));
}
templatePicker($("setupTemplate"));templatePicker($("templateSelect"));
document.querySelector("#workspace").addEventListener("change",renderStudioPreview);
for(const id of ["toSettings","backToTasks","backToInput","editAgain"])$(id).addEventListener("click",()=>queueMicrotask(renderStudioPreview));
$("fileInput").addEventListener("change",()=>$("dropZone").classList.toggle("has-files",!!state.files.length));
const personalHeading=$("savedView").querySelector("h1"); if(personalHeading)personalHeading.textContent="Моя библиотека";
const libraryHeading=$("libraryView").querySelector("h1"); if(libraryHeading)libraryHeading.textContent="Обмен материалами";
const scheduleResult=node("button","Назначить классу","button primary");scheduleResult.id="scheduleResult";scheduleResult.type="button";
scheduleResult.addEventListener("click",()=>busy("Выбираем класс",async()=>{if(state.dirty||!state.savedId)await saveCurrent();await openAssignmentForm(null,state.savedId);}));
$("step4").querySelector(".result-next-actions").append(scheduleResult);
const prepareAnswerForm=classButton("Бланк ответов A4",()=>busy("Готовим бланк",()=>enqueueJob("material_form",{edition_id:state.result.artifact_id})),"secondary");
prepareAnswerForm.id="prepareAnswerForm";prepareAnswerForm.hidden=true;$("downloadAnswerForm").after(prepareAnswerForm);
renderStudioPreview();

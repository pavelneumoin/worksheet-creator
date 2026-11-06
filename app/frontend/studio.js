"use strict";
// Small, progressively enhanced controls on top of the existing editor.
const studioTemplates = [
  ["cards", "Карточки", "Каждому заданию — своё место"],
  ["list", "Лаконичный", "Только главное, без рамок"],
  ["guided", "По шагам", "Дано, решение и ответ"],
  ["check", "С проверкой", "Место для обратной связи"],
];
function studioIcon(path) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  for (const [k, v] of Object.entries({viewBox:"0 0 24 24",fill:"none",stroke:"currentColor","stroke-width":"1.7","stroke-linecap":"round","stroke-linejoin":"round","aria-hidden":"true"})) svg.setAttribute(k,v);
  const p=document.createElementNS(svg.namespaceURI,"path"); p.setAttribute("d",path); svg.append(p); return svg;
}
const studioNavIcons={createNav:"M12 5v14M5 12h14",savedNav:"M5 3h11l3 3v15H5zM9 9h6M9 13h6M9 17h4",libraryNav:"M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",classesNav:"M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M13 4a4 4 0 0 1 0 8M22 21v-2a4 4 0 0 0-3-3.87M12 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0",scheduleNav:"M4 5h16v16H4zM16 3v4M8 3v4M4 11h16M8 15h2M14 15h2"};
for(const [id,path] of Object.entries(studioNavIcons)) $(id)?.prepend(studioIcon(path));
const studioBrandCaption=node("div","Рабочее пространство учителя","brand-caption");
document.querySelector(".brand").after(studioBrandCaption);

function addHeightControl(selectId, anchor) {
  const label=node("label", "Высота поля для решения", "field-label height-control");
  const select=node("select"); select.id=selectId;
  for(const [value,text] of [[0,"Автоматически — по макету"],[10,"1 см · короткий ответ"],[20,"2 см"],[30,"3 см"],[40,"4 см"],[50,"5 см"],[70,"7 см"],[100,"10 см · развёрнутое решение"]]) {const option=node("option",text);option.value=value;select.append(option);}
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
studioPreview.append(node("p","ВАШ МАКЕТ","eyebrow"),node("h3","Лист, который хочется решать"));
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
}
templatePicker($("setupTemplate"));templatePicker($("templateSelect"));
document.querySelector("#workspace").addEventListener("change",renderStudioPreview);
for(const id of ["toSettings","backToTasks","backToInput","editAgain"])$(id).addEventListener("click",()=>queueMicrotask(renderStudioPreview));
$("fileInput").addEventListener("change",()=>$("dropZone").classList.toggle("has-files",!!state.files.length));
const personalHeading=$("savedView").querySelector("h1"); if(personalHeading)personalHeading.textContent="Моя библиотека";
const libraryHeading=$("libraryView").querySelector("h1"); if(libraryHeading)libraryHeading.textContent="Обмен материалами";
const scheduleResult=node("button","Назначить в расписание","button primary");scheduleResult.id="scheduleResult";scheduleResult.type="button";
scheduleResult.addEventListener("click",()=>busy("Выбираем класс",async()=>{if(state.dirty||!state.savedId)await saveCurrent();await openAssignmentForm(null,state.savedId);}));
$("step4").querySelector(".download-actions").after(scheduleResult);
renderStudioPreview();

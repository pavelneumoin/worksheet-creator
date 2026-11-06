"use strict";
const batchState={current:null,assignment:null};
const batchView=node("section");batchView.id="batchView";batchView.hidden=true;document.querySelector("main").append(batchView);
const batchNav=node("button","Проверка работ","nav-button");batchNav.id="batchNav";batchNav.prepend(studioIcon("M9 11l3 3L22 4M21 12v8H3V3h14"));$("classesNav").before(batchNav);
batchNav.addEventListener("click",()=>busy("Открываем проверку",openBatchHome));
function batchHeading(title,sub) {const div=node("div",undefined,"section-title");const body=node("div");body.append(node("p","ПОСЛЕ УРОКА","eyebrow"),node("h1",title),node("p",sub,"quiet"));div.append(body);return div;}
async function openBatchHome(assignmentId = null, classId = null) {
  if(!state.auth?.authenticated){notice("Сначала войдите через MAX.",true);return;}
  showView("batch",false);batchView.replaceChildren(batchHeading("Проверить работы класса","Один PDF из МФУ. Распознаем ответы, вы подтвердите результат."));
  const classes=(await request("/api/v2/classes")).classes.filter(c=>!c.archived||c.id===classId);
  if(!classes.length){batchView.append(node("p","Сначала создайте класс и назначьте готовый лист.","empty-state"),classButton("Перейти к классам",()=>showView("classes"),"primary"));return;}
  const form=node("form",undefined,"panel batch-upload"),grid=node("div",undefined,"form-grid");
  const classSelect=node("select"),workSelect=node("select");classSelect.id="batchClass";workSelect.id="batchWork";
  for(const c of classes){const option=node("option",c.name);option.value=c.id;classSelect.append(option);}
  if(classId && classes.some(c=>c.id===classId))classSelect.value=classId;
  for(const [text,select] of [["Класс",classSelect],["Назначенная работа",workSelect]]){const label=node("label",text);label.append(select);grid.append(label);}
  const label=node("label",undefined,"upload-zone");const file=node("input");file.type="file";file.accept="application/pdf,.pdf";file.id="batchFile";
  label.append(node("span","▤","upload-icon"),node("strong","PDF со сканами работ"),node("span","До 40 страниц · до 15 МБ"),file);
  const submit=node("button","Распознать пачку","button primary");submit.type="submit";
  const recent=node("div",undefined,"batch-recent");form.append(grid,label,node("p","Код ученика на каждом листе помогает собрать страницы. Без кода вы сможете выбрать ученика сами. Сканы доступны 7 дней.","quiet"),submit);batchView.append(form,recent);
  const loadRecent=async()=>{
    recent.replaceChildren();batchState.assignment=workSelect.value;
    if(!workSelect.value)return;
    const batches=(await request(`/api/v2/assignments/${workSelect.value}/batches`)).batches;
    if(batches.length)recent.append(node("h2","Загруженные пачки"));
    for(const b of batches)recent.append(classButton(`${new Date(b.created_at).toLocaleString("ru-RU")} · ${b.photo_count||"обработка"}${b.photo_count?" стр.":""}`,()=>busy("Открываем сканы",()=>openBatch(b.id))));
  };
  const loadWorks=async()=>{
    workSelect.replaceChildren();const c=(await request("/api/v2/classes/"+classSelect.value)).classroom;
    for(const a of c.assignments.filter(a=>a.status==="active" || a.id===assignmentId)){const o=node("option",a.title);o.value=a.id;workSelect.append(o);}
    if(assignmentId && [...workSelect.options].some(o=>o.value===assignmentId))workSelect.value=assignmentId;
    submit.disabled=!workSelect.options.length;
    if(!workSelect.options.length){const o=node("option","Сначала назначьте лист этому классу");o.value="";workSelect.append(o);}
    await loadRecent();
  };
  classSelect.addEventListener("change",()=>{assignmentId=null;busy("Выбираем работу",loadWorks);});workSelect.addEventListener("change",()=>busy("Открываем пачки",loadRecent));
  form.addEventListener("submit",e=>{e.preventDefault();busy("Отправляем PDF",async()=>{
    if(!file.files.length)throw new Error("Выберите PDF со сканами.");if(file.files[0].size>15*1024*1024)throw new Error("PDF должен быть до 15 МБ.");
    const data=new FormData();data.append("assignment_id",workSelect.value);data.append("files",file.files[0]);await enqueueJob("batch_grade",data,false);
  });});await loadWorks();
}
async function openBatch(id) {
  const b=(await request("/api/v2/batches/"+id)).batch;batchState.current=b;
  showView("batch",false);batchView.replaceChildren(batchHeading(b.title,b.class_name+" · сопоставление страниц"),classButton("← Все пачки",()=>busy("Открываем пачки",openBatchHome),"ghost"));
  if(!b.pages.length){batchView.append(node("p",b.expired?"Срок хранения сканов истёк.":b.error||"Страницы обрабатываются. Результат появится в разделе «Задачи».","empty-state"));return;}
  const used=b.pages.filter(p=>p.review_id).length;
  batchView.append(node("p",`Сопоставлено ${used} из ${b.pages.length} страниц. Баллы учитываются после подтверждения.`,"batch-progress"));
  batchView.append(classButton("Результаты класса",()=>busy("Открываем отчёт",()=>openClassReport(b.assignment_id)),"secondary"));
  const form=node("form",undefined,"panel batch-mapping"),label=node("label","Код ученика"),select=node("select");select.id="batchStudent";
  const empty=node("option","Выберите ученика");empty.value="";select.append(empty);
  for(const student of b.students){const option=node("option",student.code);option.value=student.id;select.append(option);}label.append(select);
  const help=node("p","Проверьте код и отметьте все страницы одного ученика (до 5). Затем откройте распознанные ответы.","quiet");
  const grid=node("div",undefined,"batch-pages");
  for(const page of b.pages){
    const card=node("article",undefined,"batch-page"),link=node("a");link.href=`/api/v2/batches/${b.id}/photos/${page.index}`;link.target="_blank";link.rel="noopener";
    const img=node("img");img.src=link.href;img.alt="Скан страницы "+(page.index+1);img.loading="lazy";link.append(img);
    const choice=node("label"),check=node("input");check.type="checkbox";check.value=page.index;check.dataset.student=page.suggested_student_id||"";check.disabled=!!page.review_id;
    choice.append(check,node("span","Страница "+(page.index+1)));card.append(link,choice,node("p",page.student_code||"Код не прочитан","quiet"));
    if(page.warning||page.error)card.append(node("p",page.warning||page.error,"review-warning"));
    if(page.review_id)card.append(classButton("Открыть проверку",()=>busy("Открываем ответы",()=>openBatchReview(page.review_id,b)),"ghost"));
    grid.append(card);
  }
  select.addEventListener("change",()=>{for(const check of grid.querySelectorAll('input[type="checkbox"]'))check.checked=!check.disabled&&!!select.value&&check.dataset.student===select.value;});
  const first=b.pages.find(p=>!p.review_id&&p.suggested_student_id);if(first){select.value=first.suggested_student_id;select.dispatchEvent(new Event("change"));}
  const submit=node("button","Открыть ответы для проверки","button primary");submit.type="submit";
  if(used===b.pages.length){submit.disabled=true;submit.textContent="Все страницы сопоставлены";select.disabled=true;help.textContent="Откройте результаты класса или вернитесь к отдельной проверке ниже.";}
  form.append(label,help,grid,submit);batchView.append(form);
  form.addEventListener("submit",e=>{e.preventDefault();busy("Собираем работу ученика",async()=>{
    const pages=[...grid.querySelectorAll('input:checked')].map(e=>Number(e.value));
    if(!select.value||!pages.length||pages.length>5)throw new Error("Выберите ученика и от 1 до 5 его страниц.");
    const r=await request(`/api/v2/batches/${b.id}/attach`,classJson("POST",{revision:b.revision,student_id:select.value,pages}));
    await openBatchReview(r.review_id,b);
  });});
}
async function openBatchReview(reviewId,batch) {
  reviewState.batchContext={id:batch.id,assignmentId:batch.assignment_id};
  await openReview(reviewId);
}

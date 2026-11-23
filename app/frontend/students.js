"use strict";
let studentAttemptDirty=false, studentEditor=null;
function resetStudentEditor(){studentEditor?.dispose();studentEditor=null;studentAttemptDirty=false;syncClosingConfirmation();}
async function flushStudentDraft(){if(studentEditor)await studentEditor.flush();studentAttemptDirty=!!studentEditor?.dirty;}
function guardStudentLeave(action){
  if(!studentEditor?.dirty)return true;
  flushStudentDraft().then(()=>action?.()).catch(e=>notice(e.message+" Правки остаются на экране.",true));return false;
}
window.addEventListener("beforeunload",e=>{if(studentEditor?.dirty){e.preventDefault();e.returnValue="";}});
document.addEventListener("visibilitychange",()=>{if(document.hidden)flushStudentDraft().catch(()=>{});});
window.addEventListener("online",()=>flushStudentDraft().catch(()=>{}));
const pupilStatuses={submitted:"У учителя",processing:"Распознавание",needs_review:"Ожидает проверки",confirmed:"Проверено",returned:"На исправление"};
function pupilCategory(a){
  const status=a.attempts?.[0]?.status;
  if(status==="returned")return "returned";
  if(["submitted","processing","needs_review"].includes(status))return "waiting";
  if(status==="confirmed"||a.result)return "confirmed";
  return a.can_submit?"todo":"closed";
}
function pupilPriority(a){return {returned:0,todo:1,waiting:2,confirmed:3,closed:4}[pupilCategory(a)];}
function pupilLatestAttempts(attempts){
  const latest=new Map();for(const attempt of attempts){const key=attempt.assignment_id+":"+attempt.student_id,previous=latest.get(key);if(!previous||attempt.number>previous.number)latest.set(key,attempt);}return [...latest.values()];
}
function pupilPercentage(score,total){return Number.isFinite(score)&&Number.isFinite(total)&&total>0?Math.max(0,Math.min(100,Math.round(score/total*100))):null;}
function pupilDate(value){
  if(!value)return "Без срока";
  const date=new Date(/^\d{4}-\d{2}-\d{2}$/.test(String(value))?value+"T12:00:00":typeof value==="number"?value*1000:value);
  return Number.isNaN(date.getTime())?String(value):date.toLocaleDateString("ru-RU",{day:"numeric",month:"short"});
}
function pupilUploadError(files){
  if(!files.length)return "Добавьте фото или PDF.";
  if(files.length>10)return "Можно отправить до 10 фотографий за раз.";
  if(files.some(f=>!/\.(pdf|jpe?g|png)$/i.test(f.name)))return "Поддерживаются PDF, JPEG и PNG.";
  if(files.some(f=>/\.pdf$/i.test(f.name))&&files.length!==1)return "Выберите один PDF или фотографии отдельно.";
  if(files.some(f=>f.size>15*1024*1024))return "Один файл должен быть не больше 15 МБ.";
  if(files.reduce((sum,f)=>sum+f.size,0)>20*1024*1024)return "Общий размер файлов — не больше 20 МБ.";
  return "";
}
function pupilBadge(status,label){return node("span",label||pupilStatuses[status]||{todo:"К выполнению",closed:"Приём закрыт",waiting:"У учителя"}[status]||"Работа","pupil-status pupil-status--"+status);}
function pupilProgress(label,score,total){
  const block=node("div",undefined,"pupil-progress"),percent=pupilPercentage(score,total),caption=node("div",undefined,"pupil-progress-caption");
  caption.append(node("span",label),node("strong",percent===null?"—":percent+"%"));block.append(caption);
  if(percent!==null){const progress=node("progress");progress.max=100;progress.value=percent;progress.setAttribute("aria-label",label);block.append(progress);}
  return block;
}
function pupilFilters(options,onChange,initial="all"){
  const group=node("div",undefined,"pupil-filters");group.setAttribute("role","group");group.setAttribute("aria-label","Состояние работ");
  for(const [value,label,count] of options){const button=classButton("",()=>{for(const sibling of group.children)sibling.setAttribute("aria-pressed",String(sibling===button));onChange(value);},"pupil-filter");button.dataset.filter=value;button.setAttribute("aria-pressed",String(value===initial));button.append(node("span",label),node("span",String(count),"pupil-filter-count"));group.append(button);}
  return group;
}
const pupilView=node("section",undefined,"pupil-view");pupilView.id="studentView";pupilView.hidden=true;document.querySelector("main").append(pupilView);
const pupilNav=classButton("Кабинет ученика",()=>busy("Открываем работы",openStudentHome),"nav-button");pupilNav.id="studentNav";document.querySelector(".topbar nav").append(pupilNav);
pupilNav.prepend(studioIcon("M3 8l9-5 9 5-9 5zM6 10v7c4 3 8 3 12 0v-7M21 8v7"));
const studentInboxNav=classButton("От учеников",()=>busy("Открываем присланные работы",openStudentInbox),"nav-button");studentInboxNav.id="studentInboxNav";$("classesNav").after(studentInboxNav);
studentInboxNav.prepend(studioIcon("M4 4h16v16H4zM4 14h5l1 3h4l1-3h5M12 7v6M9 10l3 3 3-3"));

let pendingStudentInvite="";
try{const fragment=new URLSearchParams(location.hash.slice(1));pendingStudentInvite=fragment.get("student")||sessionStorage.getItem("listok-student-invite")||"";if(fragment.has("student")){sessionStorage.setItem("listok-student-invite",pendingStudentInvite);history.replaceState(null,"",location.pathname+location.search);}}catch{}
function renderStudentAccess(){
  pupilNav.disabled=studentInboxNav.disabled=!state.auth?.authenticated;
  if(pendingStudentInvite&&state.auth?.authenticated){queueMicrotask(()=>busy("Открываем приглашение",openStudentHome));}
}
function pupilScreen(title,teacher=false){resetStudentEditor();state.studentMode=teacher?"teacher":"pupil";showView("student",false);pupilView.replaceChildren(node("h1",title));window.scrollTo({top:0});}
function pupilFileLink(label,url){const a=node("a",label,"button secondary");a.href=url;a.target="_blank";a.rel="noopener";return a;}
function pupilStat(label,value){const card=node("div",undefined,"pupil-stat");card.append(node("strong",value),node("span",label));return card;}
async function openStudentHome(initialFilter = "all"){
  await flushStudentDraft();
  const data=(await request("/api/v2/student/assignments")).assignments;
  pupilScreen("Мои работы");
  const counts={all:data.length,todo:0,returned:0,waiting:0,confirmed:0,closed:0};data.forEach(a=>counts[pupilCategory(a)]++);
  const results=data.filter(a=>a.result),score=results.reduce((s,a)=>s+a.result.score,0),total=results.reduce((s,a)=>s+a.result.max_score,0);
  const stats=node("div",undefined,"pupil-stats");stats.append(pupilStat("К выполнению",String(counts.todo)),pupilStat("Нужно исправить",String(counts.returned)),pupilStat("У учителя",String(counts.waiting)),pupilStat("Проверено",String(counts.confirmed)));pupilView.append(stats);
  if(total){const summary=node("section",undefined,"panel pupil-overview");summary.append(pupilProgress("Баллы за проверенные работы",score,total),node("p",`${score} из ${total} баллов · работ с результатом: ${results.length}`,"quiet"));pupilView.append(summary);}
  const join=node("details",undefined,"panel pupil-join");join.open=!!pendingStudentInvite||!data.length;join.append(node("summary","Присоединиться к классу"));
  const form=node("form"),label=node("label","Приглашение учителя"),input=node("input");input.value=pendingStudentInvite;input.placeholder="Код или ссылка приглашения";input.required=true;input.autocomplete="off";label.append(input);
  const btn=node("button","Присоединиться","button primary");btn.type="submit";form.append(label,btn);form.addEventListener("submit",e=>{e.preventDefault();busy("Подключаем класс",async()=>{let token=input.value.trim();try{token=new URLSearchParams(new URL(token).hash.slice(1)).get("student")||token;}catch{}await request("/api/v2/student/join",classJson("POST",{token}));pendingStudentInvite="";sessionStorage.removeItem("listok-student-invite");await openStudentHome();notice("Класс подключён.");});});join.append(form);
  if(!data.length){pupilView.append(join,node("div","Здесь появятся работы, которые назначит учитель.","panel pupil-empty"));return;}
  const list=node("div",undefined,"pupil-cards"),listSummary=node("p",undefined,"pupil-list-summary quiet");listSummary.setAttribute("role","status");
  function draw(filter){
    list.replaceChildren();const visible=data.filter(a=>filter==="all"||pupilCategory(a)===filter).sort((a,b)=>pupilPriority(a)-pupilPriority(b)||(a.due_date||"9999").localeCompare(b.due_date||"9999"));
    listSummary.textContent=filter==="all"?"Сначала — исправления и работы к сдаче":"Работ: "+visible.length;
    for(const a of visible){
      const category=pupilCategory(a),last=a.attempts[0],card=node("article",undefined,"panel pupil-work pupil-work--"+category),top=node("div",undefined,"pupil-work-top");
      top.append(node("span",a.class_name,"pupil-class"),pupilBadge(last?.status||category));card.append(top,node("h2",a.title));
      const meta=node("p",a.due_date?"До "+pupilDate(a.due_date):"Без срока сдачи","pupil-work-meta");card.append(meta);
      if(category==="returned"&&last?.feedback)card.append(node("p",last.feedback,"pupil-feedback-excerpt"));
      if(a.result){const result=node("div",undefined,"pupil-card-result");result.append(node("strong",`${a.result.score} / ${a.result.max_score}`),node("span",["returned","waiting"].includes(category)?"предыдущий результат":"баллов"));card.append(result);}
      const action=category==="returned"&&a.can_submit?"Исправить работу":category==="todo"?"Открыть и сдать":category==="confirmed"?"Посмотреть результат":"Открыть работу";
      card.append(classButton(action,()=>busy("Открываем работу",()=>openStudentAssignment(a.id, filter)),["returned","todo"].includes(category)?"primary":"secondary"));list.append(card);
    }
    if(!visible.length)list.append(node("div",{todo:"Все работы отправлены",returned:"Нет работ на исправление",waiting:"Нет работ на проверке",confirmed:"Проверенных работ пока нет"}[filter]||"Работ пока нет","panel pupil-empty"));
  }
  pupilView.append(pupilFilters([["all","Все",counts.all],["todo","Сдать",counts.todo],["returned","Исправить",counts.returned],["waiting","У учителя",counts.waiting],["confirmed","Проверено",counts.confirmed]],draw,initialFilter),listSummary,list,join);draw(initialFilter);
}
async function openStudentAssignment(id, homeFilter = "all"){
  await flushStudentDraft();
  const a=(await request("/api/v2/student/assignments/"+id)).assignment;pupilScreen(a.title);
  const back=classButton("← Мои работы",()=>busy("Открываем работы",()=>openStudentHome(homeFilter)),"ghost pupil-back");pupilView.prepend(back);
  const last=a.attempts[0],meta=node("div",undefined,"pupil-detail-meta");meta.append(node("span",`${a.class_name} · ${a.student_code}`),node("span",a.due_date?"До "+pupilDate(a.due_date):"Без срока сдачи"),pupilBadge(last?.status||pupilCategory(a)));pupilView.append(meta);
  const sheet=node("section",undefined,"panel pupil-sheet");sheet.append(node("div",undefined,"pupil-sheet-icon"));sheet.firstChild.append(studioIcon("M6 3h8l4 4v14H6zM14 3v5h4M9 12h6M9 16h6"));const sheetText=node("div");sheetText.append(node("h2","Рабочий лист"),node("p",`${taskCount(a.tasks.length)} · PDF для печати`,"quiet"));sheet.append(sheetText,pupilFileLink("Открыть PDF",a.pdf_url));pupilView.append(sheet);
  if(a.instructions){const instructions=node("section",undefined,"panel pupil-instructions");instructions.append(node("h2","От учителя"),node("p",a.instructions));pupilView.append(instructions);}
  if(last?.feedback){const feedback=node("section",undefined,"panel pupil-feedback");feedback.append(node("h2",last.status==="returned"?"Что нужно исправить":"Комментарий учителя"),node("p",last.feedback));pupilView.append(feedback);}
  if(a.result){
    const result=node("section",undefined,"panel pupil-result"),previous=last&&["submitted","processing","needs_review","returned"].includes(last.status);result.append(node("h2",previous?"Предыдущий результат":"Результат работы"),pupilProgress("Набрано баллов",a.result.score,a.result.max_score));
    const answers=a.result.answers||[],full=answers.filter(x=>x.score===1).length,partial=answers.filter(x=>x.score>0&&x.score<1).length,zero=answers.filter(x=>x.score===0).length,breakdown=node("div",undefined,"pupil-result-breakdown");
    for(const [label,value,kind] of [["Верно",full,"correct"],["Частично",partial,"partial"],["Без балла",zero,"incorrect"]]){const item=node("span",undefined,"pupil-result-count pupil-result-count--"+kind);item.append(node("strong",String(value)),node("span",label));breakdown.append(item);}result.append(node("p",`${a.result.score} из ${a.result.max_score} баллов`,"pupil-result-total"),breakdown);
    if(a.result.comment)result.append(node("p",a.result.comment));if(previous)result.append(node("p",last.status==="returned"?"Результат обновится после проверки исправлений.":"Новая попытка ещё у учителя.","quiet"));pupilView.append(result);
  }
  if(a.can_submit)renderPupilUpload(a,id,last,homeFilter);
  else{const status=node("div",undefined,"pupil-submission-state");status.append(pupilBadge(last?.status||pupilCategory(a)),node("p",last?.status==="confirmed"?"Результат сохранён. Комментарии к заданиям — ниже.":["submitted","processing","needs_review"].includes(last?.status)?"Работа отправлена. Результат появится после проверки учителем.":"Сейчас учитель не принимает новые работы."));pupilView.append(status);}
  const tasks=node("div",undefined,"pupil-tasks");
  tasks.append(node("h2","Задания и обратная связь"));
  a.tasks.forEach((t,i)=>{const card=node("details",undefined,"panel pupil-task"),answer=a.result?.answers.find(x=>x.task_id===t.id),summary=node("summary");summary.append(node("span",`Задание ${i+1}`));if(answer)summary.append(pupilBadge(answer.score===1?"confirmed":answer.score>0?"returned":"closed",answer.score+" / 1"));card.append(summary);const q=node("div",undefined,"pupil-task-question");mathPreview(q,t.question);card.append(q);if(answer){const text=node("div");mathPreview(text,answer.text||"Ответ не записан");card.append(node("h3","Ваш ответ"),text,node("p",answer.comment|| (answer.score===1?"Выполнено верно.":"Обсудите решение с учителем.")));}const correction=last?.task_feedback?.find(x=>x.task_id===t.id);if(correction){card.append(node("h3","Что исправить"),node("p",correction.comment));card.open=true;}tasks.append(card);});pupilView.append(tasks);
  if(a.attempts.length){const history=node("details",undefined,"panel pupil-history");history.append(node("summary","История отправок · "+a.attempts.length));for(const attempt of a.attempts){const row=node("div",undefined,"pupil-history-row"),heading=node("div",undefined,"pupil-work-top");heading.append(node("strong",`Попытка ${attempt.number}`),pupilBadge(attempt.status));row.append(heading,node("p",attempt.feedback));const files=node("div",undefined,"pupil-file-actions");for(const f of attempt.files.filter(f=>!f.name.startsWith("Страница")||attempt.files.length<=10))files.append(pupilFileLink(f.name,f.url));row.append(files);history.append(row);}pupilView.append(history);}
}
function renderPupilUpload(a,id,last,homeFilter = "all"){
  const form=node("form",undefined,"panel pupil-upload"),title=node("h2",last?"Отправить исправления":"Сдать работу"),file=node("input"),camera=node("input");
  file.type="file";file.multiple=true;file.accept="image/jpeg,image/png,application/pdf";file.hidden=true;camera.type="file";camera.accept="image/jpeg,image/png";camera.setAttribute("capture","environment");camera.hidden=true;
  const tools=node("div",undefined,"pupil-upload-tools"),pick=classButton("Выбрать фото или PDF",()=>{file.value="";file.click();}),capture=classButton("Сфотографировать",()=>{camera.value="";camera.click();}),selected=node("ol",undefined,"pupil-selected-files"),status=node("p","Файлы ещё не выбраны","pupil-upload-status quiet"),send=node("button",last?"Отправить исправления":"Отправить учителю","button primary");
  status.setAttribute("role","status");send.type="submit";send.disabled=true;let chosen=[],key=crypto.randomUUID(),sending=false,delivered=false;
  function draw() {
    selected.replaceChildren();
    chosen.forEach((file, index) => {
      const row = node("li");
      const remove = classButton("Убрать", () => {
        chosen.splice(index, 1);
        key = crypto.randomUUID();
        status.classList.remove("review-warning");
        draw();
      }, "ghost");
      remove.setAttribute("aria-label", "Убрать файл " + file.name);
      remove.disabled = sending || delivered;
      row.append(node("span", file.name), remove);
      selected.append(row);
    });
    const hasPdf = chosen.some(file => /\.pdf$/i.test(file.name));
    pick.textContent = chosen.length ? (hasPdf ? "Заменить файл" : "Добавить фото") : "Выбрать фото или PDF";
    file.accept = chosen.length && !hasPdf ? "image/jpeg,image/png" : "image/jpeg,image/png,application/pdf";
    const size = (chosen.reduce((sum, file) => sum + file.size, 0) / 1024 / 1024).toFixed(1).replace(".", ",");
    status.textContent = delivered ? "Работа уже отправлена учителю" : chosen.length ? `Файлов: ${chosen.length} · ${size} МБ` : "Файлы ещё не выбраны";
    send.disabled = !chosen.length || sending || delivered;
    send.textContent = delivered ? "Работа отправлена" : sending ? "Отправляем…" : last ? "Отправить исправления" : "Отправить учителю";
    pick.disabled = sending || delivered;
    capture.disabled = hasPdf || sending || delivered;
  }
  function choose(files) {
    if (sending || delivered || !files.length) return;
    // Opening the gallery again adds pages. With a PDF the button explicitly offers replacement.
    const next = chosen.some(file => /\.pdf$/i.test(file.name)) ? [...files] : [...chosen, ...files];
    const error = pupilUploadError(next);
    if (error) {
      status.textContent = error + (chosen.length ? " Ранее выбранные файлы остались в списке." : "");
      status.classList.add("review-warning");
      return;
    }
    chosen = next;
    key = crypto.randomUUID();
    status.classList.remove("review-warning");
    draw();
  }
  file.addEventListener("change", () => choose(file.files));
  camera.addEventListener("change", () => choose(camera.files));
  tools.append(pick, capture);
  form.append(title, node("p", "Один PDF до 10 страниц или до 10 фотографий. Один файл — до 15 МБ, все вместе — до 20 МБ.", "quiet"), file, camera, tools, selected, status, send);
  form.addEventListener("submit",e=>{e.preventDefault();if(sending||delivered)return;busy("Отправляем работу",async()=>{const error=pupilUploadError(chosen);if(error)throw new Error(error);sending=true;draw();try{const body=new FormData();chosen.forEach(f=>body.append("files",f));await request(`/api/v2/student/assignments/${id}/attempts`,{method:"POST",headers:{"Idempotency-Key":key},body});delivered=true;draw();await openStudentAssignment(id,homeFilter);notice("Работа отправлена учителю.");}finally{sending=false;draw();}});});pupilView.append(form);
}
async function showPupilInvite(classroom, pupil) {
  const invitation = (await request(`/api/v2/students/${pupil.id}/invite`, {method:"POST"})).invitation;
  const dialog = node("dialog", undefined, "pupil-dialog");
  const title = node("h2", "Приглашение для " + pupil.code);
  title.id = "pupilInviteTitle";
  dialog.setAttribute("aria-labelledby", title.id);
  const code = node("input");
  code.readOnly = true;
  code.value = invitation.token;
  const link = node("input");
  link.readOnly = true;
  link.value = location.origin + "/#student=" + invitation.token;
  const codeLabel = node("label", "Код приглашения");
  const linkLabel = node("label", "Ссылка приглашения");
  codeLabel.append(code);
  linkLabel.append(link);
  const status = node("p", "", "quiet");
  status.setAttribute("role", "status");
  status.hidden = true;
  const copy = classButton("Скопировать ссылку", async () => {
    status.hidden = false;
    try {
      await navigator.clipboard.writeText(link.value);
      status.textContent = "Ссылка скопирована.";
    } catch {
      link.focus();
      link.select();
      status.textContent = "Ссылка выделена. Выберите «Копировать» в меню телефона.";
    }
  });
  dialog.append(title, node("p", "Приглашение действует 24 часа. Ученик открывает ссылку или вводит одноразовый код в своём кабинете."), codeLabel, linkLabel, status, copy, classButton("Закрыть", () => dialog.close(), "ghost"));
  document.body.append(dialog);
  dialog.addEventListener("close", () => dialog.remove());
  dialog.showModal();
}
async function openStudentInbox(previous = {}){
  await flushStudentDraft();
  const attempts=(await request("/api/v2/student-attempts")).attempts;pupilScreen("От учеников",true);
  const currentIds=new Set(pupilLatestAttempts(attempts).map(a=>a.id)),pending=a=>currentIds.has(a.id)&&["submitted","processing","needs_review"].includes(a.status),returned=a=>currentIds.has(a.id)&&a.status==="returned",stats=node("div",undefined,"pupil-stats pupil-inbox-stats");stats.append(pupilStat("Ожидают проверки",String(attempts.filter(pending).length)),pupilStat("На исправлении",String(attempts.filter(returned).length)),pupilStat("Проверено попыток",String(attempts.filter(a=>a.status==="confirmed").length)));pupilView.append(stats);
  if(attempts.length===300)pupilView.append(node("p","Показаны последние 300 отправок учеников.","quiet"));
  const controls=node("div",undefined,"panel pupil-inbox-controls"),classLabel=node("label","Класс"),classFilter=node("select"),searchLabel=node("label","Поиск"),search=node("input");search.type="search";search.placeholder="Работа или код ученика";searchLabel.append(search);
  const allClasses=node("option","Все классы");allClasses.value="";classFilter.append(allClasses);for(const name of [...new Set(attempts.map(a=>a.class_name))].sort((a,b)=>a.localeCompare(b,"ru"))){const option=node("option",name);option.value=name;classFilter.append(option);}classLabel.append(classFilter);
  classFilter.value = previous.className || "";
  if (classFilter.selectedIndex < 0) classFilter.selectedIndex = 0;
  search.value = previous.query || "";
  let active = previous.status || "pending";
  const currentFilters = () => ({className: classFilter.value, query: search.value, status: active});
  controls.append(classLabel, searchLabel, classButton("Обновить", () =>
    busy("Обновляем работы", () => openStudentInbox(currentFilters()))
  ));
  pupilView.append(controls);
  const filters=node("div"),list=node("div",undefined,"pupil-cards"),summary=node("p",undefined,"pupil-list-summary quiet");summary.setAttribute("role","status");pupilView.append(filters,summary,list);
  function draw(){
    const focusedFilter=filters.contains(document.activeElement)?document.activeElement.dataset.filter:null;
    const query=search.value.trim().toLocaleLowerCase("ru"),matches=attempts.filter(a=>(!classFilter.value||a.class_name===classFilter.value)&&(!query||(a.title+" "+a.student_code).toLocaleLowerCase("ru").includes(query)));
    filters.replaceChildren(pupilFilters([["pending","Проверить",matches.filter(pending).length],["returned","Исправляют",matches.filter(returned).length],["confirmed","Проверено",matches.filter(a=>a.status==="confirmed").length],["all","Все",matches.length]],value=>{active=value;draw();},active));
    if(focusedFilter)filters.querySelector(`[data-filter="${focusedFilter}"]`)?.focus();
    const visible=matches.filter(a=>active==="all"||(active==="pending"?pending(a):active==="returned"?returned(a):a.status===active)).sort((a,b)=>active==="pending"?a.created_at-b.created_at:b.created_at-a.created_at);list.replaceChildren();summary.textContent=visible.length?`Попыток: ${visible.length}${active==="pending"?" · сначала отправленные раньше":""}`:"";
    for(const a of visible){const card=node("article",undefined,"panel pupil-work"),top=node("div",undefined,"pupil-work-top");top.append(node("span",a.class_name+" · "+a.student_code,"pupil-class"),pupilBadge(a.status));card.append(top,node("h2",a.title),node("p",`Попытка ${a.number} · ${pupilDate(a.created_at)}`,"pupil-work-meta"));if(a.feedback)card.append(node("p",a.feedback,"pupil-feedback-excerpt"));card.append(classButton(a.status==="processing"?"Посмотреть обработку":pending(a)?"Проверить работу":"Открыть работу",()=>busy("Открываем работу",()=>openStudentAttempt(a.id, currentFilters())),pending(a)?"primary":"secondary"));list.append(card);}
    if(!visible.length){const empty=node("section",undefined,"panel pupil-empty");empty.append(node("h2",query||classFilter.value?"Ничего не найдено":active==="pending"?"Все входящие проверены":"Работ в этом разделе пока нет"));if(query||classFilter.value)empty.append(classButton("Сбросить поиск",()=>{search.value="";classFilter.value="";draw();},"secondary"));list.append(empty);}
  }
  classFilter.addEventListener("change",draw);search.addEventListener("input",draw);draw();
}
async function openStudentAttempt(id, inboxFilters = {}){
  await flushStudentDraft();
  const a=(await request("/api/v2/student-attempts/"+id)).attempt;pupilScreen(a.title,true);pupilView.prepend(classButton("← От учеников",()=>busy("Открываем работы",()=>openStudentInbox(inboxFilters)),"ghost pupil-back"));
  const meta=node("div",undefined,"pupil-detail-meta");meta.append(node("span",`${a.class_name} · ${a.student_code}`),node("span",`Попытка ${a.number}`),pupilBadge(a.status));pupilView.append(meta);
  const actions=node("div",undefined,"actions pupil-review-actions");actions.append(classButton("Обновить",()=>busy("Обновляем работу",()=>openStudentAttempt(id, inboxFilters))));
  if(["submitted","needs_review"].includes(a.status)&&a.files.length)actions.append(classButton("Распознать ответы",()=>busy("Отправляем на распознавание",async()=>{await flushStudentDraft();await request(`/api/v2/student-attempts/${id}/recognize`,{...classJson("POST",{revision:a.revision}),headers:{"Content-Type":"application/json","Idempotency-Key":crypto.randomUUID()}});await openStudentAttempt(id, inboxFilters);await refreshJobs();}),"primary"));pupilView.append(actions);
  if(a.error)pupilView.append(node("p",a.error,"job-error"));for(const w of a.warnings||[])pupilView.append(node("p",w,"review-warning"));
  const layout=node("div",undefined,"pupil-review-layout"),scans=node("section",undefined,"panel pupil-scans");scans.append(node("h2","Скан работы"));
  const pageSelect=node("select");pageSelect.setAttribute("aria-label","Страница скана");a.files.forEach((f,i)=>{const o=node("option",f.name);o.value=i;pageSelect.append(o);});scans.append(pageSelect);const preview=node("div",undefined,"pupil-scan-preview");scans.append(preview);
  function page(){preview.replaceChildren();const f=a.files[Number(pageSelect.value)];if(!f){preview.append(node("p","Сканы хранятся 7 дней."));return;}if(f.image){const img=node("img");img.src=f.url;img.alt=f.name;img.loading="lazy";preview.append(img);}preview.append(pupilFileLink("Открыть в полном размере",f.url));}pageSelect.addEventListener("change",page);page();
  const form=node("form",undefined,"pupil-marks"),inputs=[];
  for(const [i,t] of (a.tasks||[]).entries()){
    const answer=(a.draft?.answers||a.answers).find(item=>item.task_id===t.id)||{text:"",score:null,comment:""},card=node("article",undefined,"panel pupil-mark-card");card.append(node("h3","Задание "+(i+1)));const question=node("details");question.append(node("summary","Условие и ответ"));const q=node("div"),key=node("div");mathPreview(q,t.question);mathPreview(key,t.answer);question.append(q,node("strong","Ожидаемый ответ"),key);card.append(question);
    const textLabel=node("label","Ответ ученика"),text=node("textarea");text.value=answer.text;text.maxLength=2000;textLabel.append(text);
    const scoreLabel=node("label","Балл"),score=node("select");score.required=true;for(const [v,label] of [["","Не проверено"],[0,"0"],[.25,"0,25"],[.5,"0,5"],[.75,"0,75"],[1,"1"]]){const option=node("option",label);option.value=v;score.append(option);}score.value=answer.score??"";scoreLabel.append(score);
    const noteLabel=node("label","Комментарий к заданию"),note=node("textarea");note.maxLength=500;note.value=answer.comment||"";noteLabel.append(note);card.append(textLabel,scoreLabel,noteLabel);form.append(card);inputs.push({task_id:t.id,text,score,note});
  }
  if(!["submitted","needs_review"].includes(a.status))for(const item of inputs){item.text.readOnly=true;item.score.disabled=true;item.note.readOnly=true;}
  const commentLabel=node("label","Комментарий к работе"),comment=node("textarea");comment.maxLength=2000;comment.value=a.draft?.comment??a.feedback??"";commentLabel.append(comment);form.append(commentLabel);
  if(["processing","returned"].includes(a.status))comment.readOnly=true;
  const draftStatus=node("p",a.draft?"Черновик восстановлен":"Правки сохраняются автоматически","quiet pupil-save-status");draftStatus.setAttribute("role","status");
  const markingProgress=node("div",undefined,"pupil-marking-progress");function updateMarkingProgress(){const checked=inputs.filter(item=>item.score.value!=="").length;markingProgress.replaceChildren(pupilProgress(`Выставлены баллы: ${checked} из ${inputs.length}`,checked,inputs.length));}updateMarkingProgress();form.prepend(markingProgress);form.addEventListener("change",updateMarkingProgress);
  const body=()=>({revision:a.revision,comment:comment.value,answers:inputs.map(v=>({task_id:v.task_id,text:v.text.value,score:v.score.value===""?null:Number(v.score.value),comment:v.note.value,checked:true}))});
  if(["submitted","needs_review","confirmed"].includes(a.status)){
    const draftBar=node("div",undefined,"pupil-draft-bar"),tools=node("div",undefined,"actions");
    studentEditor=new StudentAutosave({revision:a.draft?.revision??null,read:body,send:async value=>{
      const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),15000);
      try{return (await request(`/api/v2/student-attempts/${id}/draft`,{...classJson("PUT",value),signal:controller.signal,keepalive:true})).draft;}finally{clearTimeout(timeout);}
    },onStatus:(status,error)=>{studentAttemptDirty=status!=="saved";syncClosingConfirmation();draftStatus.classList.toggle("review-warning",status==="error");draftStatus.textContent=status==="saved"?"Сохранено · оценка изменится после подтверждения":status==="pending"?"Сохраняем…":"Не сохранено. "+(error?.name==="AbortError"?"Нет ответа от сервера.":error?.message||"Проверьте подключение.");}});
    form.addEventListener("input",e=>{if(e.target.type!=="checkbox")studentEditor?.edit();});
    form.addEventListener("change",e=>{if(e.target.tagName==="SELECT")studentEditor?.edit();});
    tools.append(classButton("Сохранить",()=>busy("Сохраняем черновик",flushStudentDraft),"ghost"),classButton("Скачать правки",()=>{
      const url=URL.createObjectURL(new Blob([JSON.stringify(body(),null,2)],{type:"application/json"}));const link=node("a");link.href=url;link.download="Проверка-"+a.student_code+".json";link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    },"ghost"),classButton("Удалить черновик",()=>busy("Удаляем черновик",async()=>{
      if(!window.confirm("Удалить ваши правки и восстановить результат распознавания?"))return;
      await flushStudentDraft();await request(`/api/v2/student-attempts/${id}/draft`,classJson("DELETE",{revision:a.revision,draft_revision:studentEditor.revision}));resetStudentEditor();await openStudentAttempt(id, inboxFilters);
    }),"ghost"));
    const draftActions = node("details", undefined, "pupil-draft-actions");
    draftActions.append(node("summary", "Действия с черновиком"), tools);
    draftBar.append(draftStatus, draftActions);
    form.prepend(draftBar);
    if(a.draft?.stale){draftStatus.textContent="Работа изменилась. Скачайте правки перед обновлением страницы.";draftStatus.classList.add("review-warning");}
  }
  if(a.notification){const labels={queued:"Уведомление MAX в очереди",sending:"Отправляем уведомление MAX",sent:"Уведомление отправлено в MAX",demo:"Демо: уведомление не отправляется",cancelled:"Уведомление отменено: работа или доступ изменились",unavailable:"MAX не принял уведомление. Ученику нужно открыть бота и нажать «Начать».",unknown:"MAX не подтвердил доставку. Работа доступна в кабинете ученика."};pupilView.append(node("p",labels[a.notification],"quiet"));}
  const replaceCheck=node("input");replaceCheck.type="checkbox";
  if(a.base_conflict&&a.current_review){const label=node("label",undefined,"check-row");replaceCheck.required=true;label.append(replaceCheck,node("span",`Текущий результат ${a.current_review.score??"не подтверждён"}. Я сверил(а) его и заменяю результат этой попыткой.`));form.append(label);}
  if(["submitted","needs_review"].includes(a.status)){
    const verified=node("label",undefined,"check-row"),check=node("input");check.type="checkbox";check.required=true;verified.append(check,node("span","Сканы и баллы проверены"));const confirm=node("button","Подтвердить результат","button primary");confirm.type="submit";form.append(verified,confirm);
    form.addEventListener("submit",e=>{e.preventDefault();busy("Сохраняем результат",async()=>{await flushStudentDraft();await request(`/api/v2/student-attempts/${id}`,classJson("PUT",{action:"confirm",revision:a.revision,draft_revision:studentEditor?.revision??null,reviewed:check.checked,comment:comment.value,replace_review:replaceCheck.checked?a.current_review:null,answers:inputs.map(v=>({task_id:v.task_id,text:v.text.value,score:v.score.value===""?null:Number(v.score.value),comment:v.note.value,checked:true}))}));resetStudentEditor();await openStudentAttempt(id, inboxFilters);notice("Результат доступен ученику и включён в статистику.");});});
  }
  if (a.status !== "processing" && a.status !== "returned") {
    form.append(classButton("Вернуть на исправление", () => {
      if (!comment.value.trim()) {
        comment.setCustomValidity("Напишите, что нужно исправить.");
        comment.reportValidity();
        comment.setCustomValidity("");
        return;
      }
      return busy("Возвращаем работу", async () => {
        await flushStudentDraft();
        await request(`/api/v2/student-attempts/${id}`, classJson("PUT", {
          action: "return",
          revision: a.revision,
          draft_revision: studentEditor?.revision ?? null,
          feedback: comment.value,
        }));
        resetStudentEditor();
        await openStudentAttempt(id, inboxFilters);
        notice("Работа возвращена на исправление.");
      });
    }));
  }
  layout.append(scans,form);pupilView.append(layout);
  if(a.status!=="processing")renderSolutionAnalysis(pupilView,"student",a,!!a.files.length);
}
renderStudentAccess();

function showReturnToStudent(review) {
  const dialog = node("dialog", undefined, "pupil-dialog");
  const form = node("form");
  const heading = node("h2", "Работа на исправление");
  heading.id = "pupilReturnTitle";
  dialog.setAttribute("aria-labelledby", heading.id);
  const label = node("label", "Что нужно исправить");
  const text = node("textarea");
  text.required = true;
  text.maxLength = 2000;
  text.rows = 3;
  label.append(text);
  const error = node("p", "", "review-warning");
  error.setAttribute("role", "alert");
  error.hidden = true;
  const send = node("button", "Вернуть ученику", "button primary");
  send.type = "submit";
  const close = classButton("Закрыть", () => dialog.close(), "ghost");
  form.append(heading, label, error, send, close);
  dialog.append(form);
  document.body.append(dialog);
  dialog.addEventListener("close", () => dialog.remove());
  dialog.addEventListener("cancel", event => { if (send.disabled) event.preventDefault(); });
  form.addEventListener("submit", event => {
    event.preventDefault();
    if (!text.value.trim()) {
      text.setCustomValidity("Напишите, что нужно исправить.");
      text.reportValidity();
      text.setCustomValidity("");
      return;
    }
    busy("Возвращаем работу", async () => {
      send.disabled = close.disabled = true;
      text.readOnly = true;
      error.hidden = true;
      send.textContent = "Возвращаем…";
      let result;
      try {
        result = await request(`/api/v2/reviews/${review.id}/return-to-student`, classJson("POST", {
          revision: review.revision,
          feedback: text.value.trim(),
        }));
      } catch (cause) {
        error.textContent = cause.message || "Не удалось вернуть работу. Попробуйте ещё раз.";
        error.hidden = false;
        send.disabled = close.disabled = false;
        text.readOnly = false;
        send.textContent = "Вернуть ученику";
        return;
      }
      dialog.close();
      await openStudentAttempt(result.attempt.id);
    });
  });
  dialog.showModal();
}

"use strict";
let studentAttemptDirty=false;
function guardStudentLeave(){if(!studentAttemptDirty)return true;if(!window.confirm("В проверке есть несохранённые изменения. Выйти без сохранения?"))return false;studentAttemptDirty=false;return true;}
window.addEventListener("beforeunload",e=>{if(studentAttemptDirty){e.preventDefault();e.returnValue="";}});
const pupilStatuses={submitted:"У учителя",processing:"Распознавание",needs_review:"Ожидает проверки",confirmed:"Проверено",returned:"На исправление"};
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
function pupilScreen(title){showView("student",false);pupilView.replaceChildren(node("h1",title));window.scrollTo({top:0});}
function pupilFileLink(label,url){const a=node("a",label,"button secondary");a.href=url;a.target="_blank";a.rel="noopener";return a;}
function pupilStat(label,value){const card=node("div",undefined,"pupil-stat");card.append(node("strong",value),node("span",label));return card;}
async function openStudentHome(){
  if(!guardStudentLeave())return;
  const data=(await request("/api/v2/student/assignments")).assignments;
  pupilScreen("Мои работы");
  const results=data.filter(a=>a.result),score=results.reduce((s,a)=>s+a.result.score,0),total=results.reduce((s,a)=>s+a.result.max_score,0);
  const stats=node("div",undefined,"pupil-stats");stats.append(pupilStat("Назначено",String(data.length)),pupilStat("На исправление",String(data.filter(a=>a.attempts[0]?.status==="returned").length)),pupilStat("Подтверждено",String(results.length)),pupilStat("Выполнение",total?Math.round(score/total*100)+"%":"—"));pupilView.append(stats);
  const join=node("details",undefined,"panel pupil-join");join.open=!!pendingStudentInvite||!data.length;join.append(node("summary","Присоединиться к классу"));
  const form=node("form"),label=node("label","Приглашение учителя"),input=node("input");input.value=pendingStudentInvite;input.placeholder="Код или ссылка приглашения";input.required=true;input.autocomplete="off";label.append(input);
  const btn=node("button","Присоединиться","button primary");btn.type="submit";form.append(label,btn);form.addEventListener("submit",e=>{e.preventDefault();busy("Подключаем класс",async()=>{let token=input.value.trim();try{token=new URL(token).hash.split("student=")[1]||token;}catch{}await request("/api/v2/student/join",classJson("POST",{token}));pendingStudentInvite="";sessionStorage.removeItem("listok-student-invite");await openStudentHome();notice("Класс подключён.");});});join.append(form);pupilView.append(join);
  const list=node("div",undefined,"pupil-cards");
  for(const a of data){const card=node("article",undefined,"panel pupil-work");card.append(node("span",a.class_name,"eyebrow"),node("h2",a.title),node("p",a.due_date?"Сдать до "+a.due_date:"Без срока сдачи","quiet"),node("span",a.attempts[0]?pupilStatuses[a.attempts[0].status]:a.result?"Проверено":"К выполнению","pupil-status"));if(a.result)card.append(node("p",`${a.result.score} из ${a.result.max_score} баллов`,"pupil-score"));card.append(classButton("Открыть работу",()=>busy("Открываем работу",()=>openStudentAssignment(a.id)),"primary"));list.append(card);}
  if(!data.length)list.append(node("p","Работы появятся после подключения к классу.","empty-state"));pupilView.append(list);
}
async function openStudentAssignment(id){
  if(!guardStudentLeave())return;
  const a=(await request("/api/v2/student/assignments/"+id)).assignment;pupilScreen(a.title);
  pupilView.prepend(classButton("← Мои работы",()=>busy("Открываем работы",openStudentHome),"ghost"));
  pupilView.append(node("p",`${a.class_name} · ${a.student_code}${a.due_date?" · до "+a.due_date:""}`,"quiet"),pupilFileLink("Рабочий лист PDF",a.pdf_url));
  if(a.instructions)pupilView.append(node("p",a.instructions));
  const last=a.attempts[0];if(last?.feedback){const feedback=node("div",undefined,"panel pupil-feedback");feedback.append(node("h2",last.status==="returned"?"Что исправить":"Комментарий учителя"),node("p",last.feedback));pupilView.append(feedback);}
  if(a.result){const result=node("div",undefined,"panel");result.append(node("h2",`Результат: ${a.result.score} из ${a.result.max_score}`),node("p",a.result.comment));if(last&&["submitted","processing","needs_review"].includes(last.status))result.append(node("p","Новая попытка у учителя. Здесь показан предыдущий подтверждённый результат.","quiet"));pupilView.append(result);}
  const tasks=node("div",undefined,"pupil-tasks");
  a.tasks.forEach((t,i)=>{const card=node("details",undefined,"panel pupil-task"),answer=a.result?.answers.find(x=>x.task_id===t.id);card.append(node("summary",`Задание ${i+1}${answer?" · "+answer.score+" / 1":""}`));const q=node("div");mathPreview(q,t.question);card.append(q);if(answer){const text=node("div");mathPreview(text,answer.text||"Ответ не записан");card.append(node("h3","Ваш ответ"),text,node("p",answer.comment|| (answer.score===1?"Выполнено верно.":"Посмотрите комментарий к работе или уточните у учителя.")));}tasks.append(card);});pupilView.append(tasks);
  if(a.can_submit){
    const form=node("form",undefined,"panel pupil-upload"),title=node("h2",last?"Отправить исправление":"Сдать работу"),label=node("label","Фото страниц или PDF"),file=node("input");file.type="file";file.multiple=true;file.accept="image/jpeg,image/png,application/pdf";file.required=true;label.append(file);
    const camera=node("input");camera.type="file";camera.accept="image/jpeg,image/png";camera.setAttribute("capture","environment");camera.hidden=true;
    const selected=node("p","Один PDF до 10 страниц или до 10 фото. Всего до 20 МБ.","quiet");let chosen=[],key=crypto.randomUUID();
    const choose=files=>{chosen=[...files];key=crypto.randomUUID();selected.textContent=chosen.map(f=>f.name).join(", ");file.required=false;};file.addEventListener("change",()=>choose(file.files));camera.addEventListener("change",()=>choose(camera.files));
    const send=node("button",last?"Отправить исправление":"Отправить учителю","button primary");send.type="submit";
    form.append(title,label,camera,classButton("Сфотографировать",()=>camera.click()),selected,send);form.addEventListener("submit",e=>{e.preventDefault();busy("Отправляем работу",async()=>{if(!chosen.length)throw new Error("Добавьте фото или PDF.");if(chosen.length>10||chosen.reduce((s,f)=>s+f.size,0)>20*1024*1024)throw new Error("Выберите до 10 фото общим размером до 20 МБ.");const body=new FormData();chosen.forEach(f=>body.append("files",f));await request(`/api/v2/student/assignments/${id}/attempts`,{method:"POST",headers:{"Idempotency-Key":key},body});await openStudentAssignment(id);notice("Работа отправлена учителю.");});});pupilView.append(form);
  }else pupilView.append(node("p",last?pupilStatuses[last.status]:"Приём работ закрыт.","pupil-status"));
  if(a.attempts.length){const history=node("details",undefined,"panel");history.append(node("summary","История попыток · "+a.attempts.length));for(const attempt of a.attempts){const row=node("div",undefined,"pupil-history-row");row.append(node("strong",`Попытка ${attempt.number} · ${pupilStatuses[attempt.status]}`),node("p",attempt.feedback));for(const f of attempt.files.filter(f=>!f.name.startsWith("Страница")||attempt.files.length<=10))row.append(pupilFileLink(f.name,f.url));history.append(row);}pupilView.append(history);}
}
async function showPupilInvite(classroom,pupil){
  const invitation=(await request(`/api/v2/students/${pupil.id}/invite`,{method:"POST"})).invitation;
  const dialog=node("dialog",undefined,"pupil-dialog");const code=node("input");code.readOnly=true;code.value=invitation.token;
  const link=node("input");link.readOnly=true;link.value=location.origin+"/#student="+invitation.token;
  const c=node("label","Код приглашения"),l=node("label","Ссылка приглашения");c.append(code);l.append(link);
  const close=classButton("Закрыть",()=>dialog.close(),"ghost");dialog.append(node("h2",pupil.code),node("p","Приглашение действует 24 часа и используется один раз. Ученик входит через MAX и вводит код в разделе «Кабинет ученика»."),c,l,classButton("Скопировать приглашение",async()=>{try{await navigator.clipboard.writeText(link.value);notice("Ссылка скопирована.");}catch{link.select();}}),close);document.body.append(dialog);dialog.addEventListener("close",()=>dialog.remove());dialog.showModal();
}
async function openStudentInbox(){
  if(!guardStudentLeave())return;
  const attempts=(await request("/api/v2/student-attempts")).attempts;pupilScreen("От учеников");
  const controls=node("div",undefined,"actions"),filter=node("select");filter.setAttribute("aria-label","Состояние работы");for(const [value,label] of [["pending","Ожидают проверки"],["returned","На исправлении"],["all","Все попытки"]]){const option=node("option",label);option.value=value;filter.append(option);}controls.append(filter,classButton("Обновить",()=>busy("Обновляем работы",openStudentInbox)));pupilView.append(controls);
  const list=node("div",undefined,"pupil-cards");pupilView.append(list);
  function draw(){list.replaceChildren();for(const a of attempts.filter(a=>filter.value==="all"||(filter.value==="returned"?a.status==="returned":["submitted","processing","needs_review"].includes(a.status)))){const card=node("article",undefined,"panel pupil-work");card.append(node("span",a.class_name+" · "+a.student_code,"eyebrow"),node("h2",a.title),node("p",`Попытка ${a.number} · ${pupilStatuses[a.status]}`,"quiet"),classButton("Открыть проверку",()=>busy("Открываем работу",()=>openStudentAttempt(a.id)),"primary"));list.append(card);}if(!list.children.length)list.append(node("p","Новых работ нет.","empty-state"));}filter.addEventListener("change",draw);draw();
}
async function openStudentAttempt(id){
  if(!guardStudentLeave())return;
  const a=(await request("/api/v2/student-attempts/"+id)).attempt;pupilScreen(a.title);pupilView.prepend(classButton("← От учеников",()=>busy("Открываем работы",openStudentInbox),"ghost"));
  pupilView.append(node("p",`${a.class_name} · ${a.student_code} · попытка ${a.number} · ${pupilStatuses[a.status]}`,"quiet"));
  const actions=node("div",undefined,"actions");actions.append(classButton("Обновить",()=>busy("Обновляем работу",()=>openStudentAttempt(id))));
  if(["submitted","needs_review"].includes(a.status)&&a.files.length)actions.append(classButton("Распознать ответы",()=>busy("Отправляем на распознавание",async()=>{if(!guardStudentLeave())return;await request(`/api/v2/student-attempts/${id}/recognize`,{...classJson("POST",{revision:a.revision}),headers:{"Content-Type":"application/json","Idempotency-Key":crypto.randomUUID()}});await openStudentAttempt(id);await refreshJobs();}),"primary"));pupilView.append(actions);
  if(a.error)pupilView.append(node("p",a.error,"job-error"));for(const w of a.warnings||[])pupilView.append(node("p",w,"review-warning"));
  const layout=node("div",undefined,"pupil-review-layout"),scans=node("section",undefined,"panel pupil-scans");scans.append(node("h2","Скан работы"));
  const pageSelect=node("select");pageSelect.setAttribute("aria-label","Страница скана");a.files.forEach((f,i)=>{const o=node("option",f.name);o.value=i;pageSelect.append(o);});scans.append(pageSelect);const preview=node("div",undefined,"pupil-scan-preview");scans.append(preview);
  function page(){preview.replaceChildren();const f=a.files[Number(pageSelect.value)];if(!f){preview.append(node("p","Сканы хранятся 7 дней."));return;}if(f.image){const img=node("img");img.src=f.url;img.alt=f.name;img.loading="lazy";preview.append(img);}preview.append(pupilFileLink("Открыть в полном размере",f.url));}pageSelect.addEventListener("change",page);page();
  const form=node("form",undefined,"pupil-marks"),inputs=[];
  for(const [i,t] of (a.tasks||[]).entries()){
    const answer=a.answers[i],card=node("article",undefined,"panel");card.append(node("h3","Задание "+(i+1)));const question=node("details");question.append(node("summary","Условие и ответ"));const q=node("div"),key=node("div");mathPreview(q,t.question);mathPreview(key,t.answer);question.append(q,node("strong","Ожидаемый ответ"),key);card.append(question);
    const textLabel=node("label","Ответ ученика"),text=node("textarea");text.value=answer.text;text.maxLength=2000;textLabel.append(text);
    const scoreLabel=node("label","Балл"),score=node("select");for(const [v,label] of [["","Не проверено"],[0,"0"],[.25,"0,25"],[.5,"0,5"],[.75,"0,75"],[1,"1"]]){const option=node("option",label);option.value=v;score.append(option);}score.value=answer.score??"";scoreLabel.append(score);
    const noteLabel=node("label","Комментарий к заданию"),note=node("textarea");note.maxLength=500;note.value=answer.comment||"";noteLabel.append(note);card.append(textLabel,scoreLabel,noteLabel);form.append(card);inputs.push({task_id:t.id,text,score,note});
  }
  form.addEventListener("input",()=>{studentAttemptDirty=true;});form.addEventListener("change",()=>{studentAttemptDirty=true;});
  if(!["submitted","needs_review"].includes(a.status))for(const item of inputs){item.text.readOnly=true;item.score.disabled=true;item.note.readOnly=true;}
  const commentLabel=node("label","Комментарий к работе"),comment=node("textarea");comment.maxLength=2000;comment.value=a.feedback||"";commentLabel.append(comment);form.append(commentLabel);
  if(["processing","returned"].includes(a.status))comment.readOnly=true;
  const replaceCheck=node("input");replaceCheck.type="checkbox";
  if(a.base_conflict&&a.current_review){const label=node("label",undefined,"check-row");replaceCheck.required=true;label.append(replaceCheck,node("span",`Текущий результат ${a.current_review.score??"не подтверждён"}. Я сверил(а) его и заменяю результат этой попыткой.`));form.append(label);}
  if(["submitted","needs_review"].includes(a.status)){
    const verified=node("label",undefined,"check-row"),check=node("input");check.type="checkbox";check.required=true;verified.append(check,node("span","Сканы и баллы проверены"));const confirm=node("button","Подтвердить результат","button primary");confirm.type="submit";form.append(verified,confirm);
    form.addEventListener("submit",e=>{e.preventDefault();busy("Сохраняем результат",async()=>{await request(`/api/v2/student-attempts/${id}`,classJson("PUT",{action:"confirm",revision:a.revision,reviewed:check.checked,comment:comment.value,replace_review:replaceCheck.checked?a.current_review:null,answers:inputs.map(v=>({task_id:v.task_id,text:v.text.value,score:v.score.value===""?null:Number(v.score.value),comment:v.note.value,checked:true}))}));studentAttemptDirty=false;await openStudentAttempt(id);notice("Результат доступен ученику и включён в статистику.");});});
  }
  if(a.status!=="processing"&&a.status!=="returned")form.append(classButton("Вернуть на исправление",()=>busy("Возвращаем работу",async()=>{if(!comment.value.trim())throw new Error("Напишите в комментарии, что нужно исправить.");await request(`/api/v2/student-attempts/${id}`,classJson("PUT",{action:"return",revision:a.revision,feedback:comment.value}));studentAttemptDirty=false;await openStudentAttempt(id);notice("Ученик может отправить новую попытку.");})));
  layout.append(scans,form);pupilView.append(layout);
  if(a.status!=="processing")renderSolutionAnalysis(pupilView,"student",a,!!a.files.length);
}
renderStudentAccess();

function showReturnToStudent(review){
  const dialog=node("dialog",undefined,"pupil-dialog"),form=node("form"),label=node("label","Что нужно исправить"),text=node("textarea");text.required=true;text.maxLength=2000;label.append(text);const send=node("button","Вернуть ученику","button primary");send.type="submit";form.append(node("h2","Работа на исправление"),label,send,classButton("Закрыть",()=>dialog.close(),"ghost"));dialog.append(form);document.body.append(dialog);dialog.addEventListener("close",()=>dialog.remove());form.addEventListener("submit",e=>{e.preventDefault();busy("Возвращаем работу",async()=>{const result=await request(`/api/v2/reviews/${review.id}/return-to-student`,classJson("POST",{revision:review.revision,feedback:text.value}));dialog.close();await openStudentAttempt(result.attempt.id);});});dialog.showModal();
}

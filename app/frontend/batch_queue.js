"use strict";
const batchQueueState = {data:null, focus:null};

function nextQueueItem(items, current, direction = 1, unresolved = false) {
  if (!items.length) return null;
  const at = items.findIndex(i => i.review_id === current?.review_id && i.task_id === current?.task_id);
  for (let step = 1; step <= items.length; step++) {
    const i = ((at < 0 ? (direction > 0 ? -1 : 0) : at) + direction * step + items.length * 2) % items.length;
    if (!unresolved || !items[i].resolved) return items[i];
  }
  return null;
}
function queueAction(text, action, cls = "secondary") {
  return classButton(text, () => busy(text, action), cls);
}
async function queueData(id) {
  await flushReviewDraft();
  const data=(await request(`/api/v2/batches/${id}/queue`)).queue;
  batchQueueState.data=data;
  return data;
}
async function openBatchQueue(id) {
  const q=await queueData(id);
  reviewState.queueContext=null;
  resetReviewEditor();
  showView("batch",false);
  batchView.replaceChildren(batchHeading("Очередь проверки",q.class_name+" · "+q.title),
    queueAction("← К страницам PDF",()=>openBatch(id),"ghost back-link"));
  const summary=node("section",undefined,"queue-summary panel");
  summary.append(node("h2",q.remaining ? `Нужно внимание: ${q.remaining}` : "Сомнительных ответов не осталось"));
  const counts=node("div",undefined,"queue-counts");
  for (const [number,label] of [[q.remaining,"нужно проверить"],[q.ready,"к подтверждению"],[q.confirmed,"подтверждено"]]) {
    const cell=node("div");cell.append(node("strong",String(number)),node("span",label));counts.append(cell);
  }
  summary.append(counts);
  if(q.remaining) summary.append(queueAction("Продолжить проверку",()=>openQueueAnswer(q.items.find(i=>!i.resolved)),"primary"));
  if(!q.remaining && !q.reviews.length)summary.querySelector("h2").textContent="Подготовьте страницы к проверке";
  batchView.append(summary);
  if(q.proposals.length){
    const prepare=node("section",undefined,"panel queue-prepare");
    prepare.append(node("h2",`По QR найдены работы: ${q.proposals.length}`),node("p","Сверьте коды на страницах. Ответы уже распознаны.","quiet"));
    const details=node("details");details.open=true;details.append(node("summary","Страницы и ученики"));
    const rows=node("div",undefined,"queue-mapping-rows");
    for(const p of q.proposals){const row=node("div");const link=node("a",`Страница ${p.page+1}`);link.href=`/api/v2/batches/${id}/photos/${p.page}`;link.target="_blank";link.rel="noopener";row.append(link,node("strong",p.student_code));rows.append(row);}
    details.append(rows);prepare.append(details);
    const label=node("label",undefined,"queue-attestation"),check=node("input");check.type="checkbox";
    label.append(check,node("span","Коды учеников и страницы сопоставлены верно"));prepare.append(label);
    const start=queueAction("Собрать очередь",async()=>{
      await request(`/api/v2/batches/${id}/queue/prepare`,classJson("POST",{revision:q.revision,mapping_reviewed:check.checked}));
      await openBatchQueue(id);
    },"primary");start.disabled=true;check.addEventListener("change",()=>start.disabled=!check.checked);prepare.append(start);batchView.append(prepare);
  }
  if(q.blocked.length || q.reviews.some(r=>!r.usable&&!r.confirmed)){
    const blocked=node("section",undefined,"panel queue-blocked");blocked.append(node("h2","Нужно сопоставить вручную"));
    for(const p of q.blocked)blocked.append(node("p",`Страница ${p.page+1}: ${p.reason}.`,"quiet"));
    for(const r of q.reviews.filter(r=>!r.usable&&!r.confirmed))blocked.append(queueAction(r.student_code+" · открыть проверку",()=>openQueueReview(r.id)));
    blocked.append(queueAction("Перейти к страницам",()=>openBatch(id)));batchView.append(blocked);
  }
  if(q.expired)batchView.append(node("p","Срок хранения сканов истёк. Сверьте работу с бумажным оригиналом перед подтверждением.","review-warning"));
  if(q.reviews.length){
    const works=node("section",undefined,"queue-works");works.append(node("h2","Работы учеников"));
    for(const r of q.reviews){
      const row=node("article",undefined,"queue-work");const body=node("div");
      body.append(node("strong",r.student_code),node("span",r.confirmed?"Подтверждено":!r.usable?"Нужна сверка":r.attention?`Нужно внимание: ${r.attention}`:"Готово к подтверждению","quiet"));
      row.append(body,queueAction(r.confirmed?"Открыть":r.ready?"Сверить итог":"Ответы",()=>openQueueReview(r.id)));works.append(row);
    }
    batchView.append(works);
  }
  batchView.append(queueAction("Обновить очередь",()=>openBatchQueue(id),"ghost"));
  batchView.querySelector("h1").tabIndex=-1;batchView.querySelector("h1").focus({preventScroll:true});window.scrollTo({top:0});
}
async function openQueueReview(reviewId, item = null) {
  const q=batchQueueState.data;
  await flushReviewDraft();
  reviewState.queueContext={id:q.id,assignmentId:q.assignment_id,reviewId,item};
  reviewState.batchContext={id:q.id,assignmentId:q.assignment_id};
  await openReview(reviewId);
}
async function openQueueAnswer(item) {
  if(!item) return openBatchQueue(batchQueueState.data.id);
  batchQueueState.focus=item;
  await openQueueReview(item.review_id,item);
}
function mountBatchQueueFocus(form,fields,controls,r,refreshTotal) {
  const context=reviewState.queueContext,q=batchQueueState.data,current=context.item;
  const bar=node("section",undefined,"queue-answer-bar");
  bar.append(node("strong",`Осталось ${q.remaining} · ${q.class_name}`),queueAction("Вся очередь",()=>openBatchQueue(q.id),"ghost"));
  form.prepend(bar);
  if(!current){ mountReviewFocus(form,fields,controls,r,refreshTotal);return; }
  const index=fields.findIndex(f=>f.id===current.task_id);
  if(index<0){mountReviewFocus(form,fields,controls,r,refreshTotal);return;}
  const field=fields[index];fields.forEach((f,i)=>f.card.hidden=i!==index);
  form.classList.add("queue-answer-form");
  const caption=node("p",`${r.student_code} · задание ${index+1} из ${fields.length}`,"queue-answer-identity");bar.after(caption);
  caption.append(node("small","Версия "+r.edition_code));
  if(r.warnings.length){const warnings=node("details",undefined,"queue-warnings");warnings.append(node("summary",`Замечания к работе · ${r.warnings.length}`));for(const text of r.warnings)warnings.append(node("p",text,"review-warning"));caption.after(warnings);}
  form.querySelector("h2").textContent=current.reason==="empty"?"Пустое поле":current.reason==="unclear"?"Неразборчивый ответ":"Сверьте ответ";
  if(r.photos.length){
    const answer=field.answer,source=answer.sources?.find(s=>Number.isInteger(s.photo_index)&&r.photos[s.photo_index]),box=reviewBox(source?.box);
    const preview=classButton("",()=>openReviewScan(r,answer,index+1),"queue-scan-preview");preview.setAttribute("aria-label","Увеличить фрагмент ответа");
    const canvas=node("canvas");const image=new Image();image.alt="";
    image.onload=()=>{const b=box||[0,0,1000,1000],pad=box?12:0;const x=Math.max(0,b[0]-pad)/1000*image.naturalWidth,y=Math.max(0,b[1]-pad)/1000*image.naturalHeight;
      const w=Math.min(image.naturalWidth-x,(b[2]-b[0]+2*pad)/1000*image.naturalWidth),h=Math.min(image.naturalHeight-y,(b[3]-b[1]+2*pad)/1000*image.naturalHeight);
      const scale=Math.min(2,900/w,320/h);canvas.width=Math.max(1,Math.round(w*scale));canvas.height=Math.max(1,Math.round(h*scale));canvas.getContext("2d").drawImage(image,x,y,w,h,0,0,canvas.width,canvas.height);};
    image.onerror=()=>{preview.replaceChildren(node("span","Открыть оригинал скана"));};image.src=r.photos[source?.photo_index??0];
    preview.append(canvas,node("span","Нажмите, чтобы увеличить"));field.card.querySelector(".review-answer-top").after(preview);
  }
  const nav=node("div",undefined,"review-focus-nav queue-focus-nav");
  const go=async(direction,complete=false)=>{
    if(complete){if(field.score.value==="")throw new Error("Сначала выберите баллы.");field.checked=true;editReviewDraft();refreshTotal();}
    const fresh=await queueData(q.id);
    const next=nextQueueItem(fresh.items,current,direction,direction>0);
    if(next)await openQueueAnswer(next);else await openBatchQueue(q.id);
  };
  const previous=classButton("←",()=>busy("Предыдущий ответ",()=>go(-1)));previous.setAttribute("aria-label","Предыдущий ответ в пачке");
  const done=queueAction("Проверено, дальше",()=>go(1,true),"primary");
  const skip=queueAction("Пропустить",()=>go(1));
  const update=()=>done.disabled=field.score.value==="";field.score.addEventListener("change",update);field.text.addEventListener("input",update);update();
  nav.append(previous,done,skip);field.card.after(nav);
  const more=node("details",undefined,"queue-work-details");more.append(node("summary","Итог работы и восстановление правок"));controls.before(more);more.append(controls);
  const full=queueAction("Все ответы ученика",()=>openQueueReview(r.id),"secondary");nav.after(full);
  field.card.querySelector("h3").tabIndex=-1;
  // Keep failed autosaves visible even while the work-level confirmation is collapsed.
  nav.after(reviewState.editor.status);
}
if(typeof module!=="undefined")module.exports={nextQueueItem};

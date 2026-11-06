"use strict";
function renderSolutionAnalysis(target,kind,data,hasScans){
  const box=node("details",undefined,"panel solution-analysis");box.append(node("summary","Развёрнутое решение"));
  const current=data.solution_analysis;
  if(hasScans){box.append(classButton(current?"Повторить анализ решения":"Анализировать ход решения",()=>busy("Отправляем решение",async()=>{
    if(kind==="review")await flushReviewDraft();
    if(kind==="student")await flushStudentDraft();
    await request(`/api/v2/solution-analysis/${kind}/${data.id}`,{method:"POST",headers:{"Idempotency-Key":crypto.randomUUID()}});
    await refreshJobs();notice("Анализ выполняется. Результат появится в задачах.");
  }),"secondary"));}
  if(current){
    box.open=true;
    box.append(node("p",current.stale?"Работа изменилась после анализа. Рекомендации относятся к предыдущей версии.":current.scale,"quiet"));
    for(const [i,t] of current.tasks.entries()){
      const card=node("article",undefined,"solution-note");card.append(node("h3",`Задание ${i+1} · ${t.suggested_score===null?"нужна проверка":t.suggested_score+" / 1 — рекомендация"}`));
      if(t.evidence){const quote=node("blockquote");mathPreview(quote,t.evidence);card.append(quote);}
      card.append(node("p",t.reason),node("p",t.next_step,"quiet"));box.append(card);
    }
    const source=node("details");source.append(node("summary","Методические источники"));for(const s of current.sources||[]){const link=node("a",s.title);link.href=s.url;link.target="_blank";link.rel="noopener";source.append(link,node("br"));}if(current.sources?.length)box.append(source);
    const transcript=node("details");transcript.append(node("summary","Расшифровка сканов"));for(const t of current.transcription){transcript.append(node("h3",`Страница ${t.page} · задание ${t.number}`));const text=node("div");mathPreview(text,t.text);transcript.append(text);}box.append(transcript);
  }else box.append(node("p","Проверка шагов и обоснования по полным сканам. Баллы подтверждает учитель.","quiet"));
  target.append(box);
}

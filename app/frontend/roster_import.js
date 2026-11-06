"use strict";
// Names stay in this DOM only: the API receives a count and a class revision.
function renderLocalRosterImport(target, classroom) {
  const box=node("details",undefined,"panel roster-import"),form=node("form");
  box.append(node("summary","Создать коды из списка учеников"));
  const label=node("label","Вставьте список: один ученик на строку"),input=node("textarea");
  input.rows=6;input.maxLength=12000;input.placeholder="Иванов Иван\nПетрова Анна";input.autocomplete="off";label.append(input);
  const hint=node("p","Имена останутся на этом устройстве. На сервер отправится только количество учеников. Таблицу «имя → код» скачайте и сохраните у себя.","quiet");
  const preview=node("p",undefined,"quiet"),result=node("div"),submit=node("button","Создать коды и подготовить таблицу","button primary");submit.type="submit";
  const names=()=>input.value.split(/\r?\n/).map(s=>s.trim().replace(/^\d+[.)]\s*/,"")).filter(Boolean);
  input.addEventListener("input",()=>{preview.textContent=`В списке: ${names().length}. Добавление создаёт новых учеников, не заменяя существующих.`;});
  let mapping=null;
  form.addEventListener("submit",async e=>{
    e.preventDefault();const rows=names();
    if(!rows.length||rows.length>100||rows.some(s=>s.length>120))return notice("Нужно от 1 до 100 строк, до 120 символов в строке.",true);
    submit.disabled=true;input.disabled=true;
    await busy("Создаём постоянные коды",async()=>{
      const before=await request(`/api/v2/classes/${classroom.id}`),ids=new Set(before.classroom.students.map(s=>s.id));let after;
      try{after=(await request(`/api/v2/classes/${classroom.id}/students`,classJson("POST",{revision:before.classroom.revision,count:rows.length}))).classroom;}
      catch(error){
        after=(await request(`/api/v2/classes/${classroom.id}`)).classroom;
        if(after.revision!==before.classroom.revision+1||after.students.filter(s=>!ids.has(s.id)).length!==rows.length)throw error;
      }
      const added=after.students.filter(s=>!ids.has(s.id));
      if(added.length!==rows.length)throw new Error("Список изменился на другом устройстве. Обновите класс; повторно коды не создавались.");
      mapping=added.map((s,i)=>[s.code,rows[i]]);classState.current=after;
      const countLabel=target.querySelector('.class-heading .quiet');
      if(countLabel)countLabel.textContent=`Учеников: ${after.student_count} · Активных работ: ${after.assignment_count}`;
      const download=classButton("Скачать таблицу имён и кодов",()=>{
        const cell=s=>'"'+(/^[=+@\-\t\r]/.test(s)?"'":"")+s.replaceAll('"','""')+'"';
        const csv="\uFEFF"+[["Код ученика","ФИО"],...mapping].map(row=>row.map(cell).join(";")).join("\r\n");
        const url=URL.createObjectURL(new Blob([csv],{type:"text/csv;charset=utf-8"})),a=node("a");
        a.href=url;a.download="Ученики — "+classroom.name.replace(/[<>:\"/\\|?*]/g,"_")+".csv";a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);
      },"primary");
      result.replaceChildren(node("p",`Кодов создано: ${mapping.length}. Скачайте таблицу до перехода на другую страницу — имена нигде не сохраняются.`),download,classButton("Таблица сохранена — открыть класс",()=>busy("Открываем класс",()=>openClass(classroom.id))));
      input.value="";label.hidden=true;submit.hidden=true;preview.hidden=true;
    });
    if(!mapping){submit.disabled=false;input.disabled=false;}
  });
  form.append(label,hint,preview,submit,result);box.append(form);target.append(box);
}

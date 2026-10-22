"use strict";
$("scheduleMonth").value = new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Europe/Moscow",
  year: "numeric",
  month: "2-digit",
}).format(new Date());

async function refreshSchedule() {
  const month = $("scheduleMonth").value;
  if (!/^\d{4}-\d{2}$/.test(month))
    throw new Error("Выберите месяц расписания.");
  const data = await request("/api/v2/schedule?month=" + month);
  const [year, number] = month.split("-").map(Number);
  const count = new Date(year, number, 0).getDate();
  const offset = (new Date(year, number - 1, 1).getDay() + 6) % 7;
  const grid = $("monthGrid");
  grid.replaceChildren();
  for (const day of ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"])
    grid.append(node("span", day, "calendar-weekday"));
  for (let i = 0; i < offset; i++)
    grid.append(node("span", "", "calendar-empty"));
  const today = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Europe/Moscow",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
  for (let day = 1; day <= count; day++) {
    const date = month + "-" + String(day).padStart(2, "0");
    const assignments = data.assignments.filter(
      (a) => a.scheduled_date === date,
    );
    const cell = node("span", String(day), "calendar-day");
    if (date === today) cell.classList.add("today");
    if (assignments.length) cell.classList.add("has-work");
    cell.setAttribute(
      "aria-label",
      assignmentDate(date) +
        (assignments.length ? `, работ: ${assignments.length}` : ""),
    );
    grid.append(cell);
  }
  const list = $("scheduleList");
  list.replaceChildren();
  for (const a of data.assignments) {
    const card = node("article", undefined, "saved-card schedule-work");
    card.append(
      node(
        "p",
        `${assignmentDate(a.scheduled_date)} · ${a.class_name}`,
        "eyebrow",
      ),
      node("h2", a.title),
      node(
        "p",
        `${a.status === "closed" ? "Закрыта" : "Назначена"} · учеников: ${a.student_count}` +
          (a.due_date ? ` · сдать до ${assignmentDate(a.due_date)}` : ""),
        "quiet",
      ),
      classButton("Открыть работу", () =>
        busy("Открываем работу", () => openAssignment(a.id)),
      ),
    );
    list.append(card);
  }
  if (!data.assignments.length)
    list.append(
      node(
        "p",
        "На этот месяц работ пока нет. При назначении листа классу укажите дату проведения.",
        "empty-state",
      ),
    );
}
$("scheduleNav").addEventListener("click", () => showView("schedule"));
$("scheduleClasses").addEventListener("click", () => showView("classes"));
$("scheduleMonth").addEventListener("change", () =>
  busy("Обновляем расписание", refreshSchedule),
);
function changeMonth(delta) {
  const [year, month] = $("scheduleMonth").value.split("-").map(Number);
  const date = new Date(year, month - 1 + delta, 1);
  $("scheduleMonth").value =
    `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
  return busy("Обновляем расписание", refreshSchedule);
}
$("previousMonth").addEventListener("click", () => changeMonth(-1));
$("nextMonth").addEventListener("click", () => changeMonth(1));

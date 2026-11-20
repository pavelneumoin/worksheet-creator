"use strict";
// The same navigation actions power desktop and a reachable phone tab bar.
const mobileMore = node("button", "Ещё", "nav-button mobile-more-nav");
mobileMore.id = "mobileMoreNav";
mobileMore.setAttribute("aria-haspopup", "dialog");
mobileMore.setAttribute("aria-label", "Ещё");
for(const [id,label] of [["createNav","Создать лист"],["savedNav","Моя библиотека"],["batchNav","Проверка работ"],["classesNav","Классы"]])$(id).setAttribute("aria-label",label);
mobileMore.prepend(listokIcon("ellipsis"));
document.querySelector(".topbar nav").append(mobileMore);
const mobileMenu = node("dialog", undefined, "mobile-menu");
mobileMenu.setAttribute("aria-labelledby", "mobileMenuTitle");
const mobileMenuHead = node("div", undefined, "mobile-menu-heading");
const mobileMenuTitle = node("h2", "Рабочее пространство"); mobileMenuTitle.id = "mobileMenuTitle";
const mobileMenuClose = node("button", undefined, "button ghost icon-button");
mobileMenuClose.setAttribute("aria-label", "Закрыть меню");
mobileMenuClose.title = "Закрыть меню";
mobileMenuClose.append(listokIcon("close"));
mobileMenuClose.addEventListener("click", () => mobileMenu.close());
mobileMenuHead.append(mobileMenuTitle, mobileMenuClose); mobileMenu.append(mobileMenuHead);
for (const [id, title, hint, icon] of [["studentInboxNav", "От учеников", "Присланные работы и исправления", "inbox"], ["studentNav", "Кабинет ученика", "Мои задания и результаты", "graduationCap"], ["scheduleNav", "Расписание", "Работы и печать к уроку", "calendar"], ["analyticsNav", "Статистика", "Результаты и темы", "chart"], ["schoolNav", "Моя школа", "Учителя и отчёт завуча", "school"], ["libraryNav", "Обмен материалами", "Листы других учителей", "sharedLibrary"], ["feedbackNav", "Отзывы", "Оценка и предложения коллег", "message"]]) {
  const button = node("button", undefined, "mobile-menu-item");
  button.type = "button";
  const copy = node("span", undefined, "mobile-menu-copy");
  copy.append(node("strong", title), node("span", hint));
  button.append(listokIcon(icon, {className: "mobile-menu-icon"}), copy, listokIcon("chevronRight", {size: 16, className: "mobile-menu-chevron"}));
  button.addEventListener("click", () => { mobileMenu.close(); $(id).click(); });
  mobileMenu.append(button);
}
mobileMenu.addEventListener("click", e => { if (e.target === mobileMenu) mobileMenu.close(); });
document.body.append(mobileMenu);
mobileMore.addEventListener("click", () => mobileMenu.showModal());

"use strict";
// The same navigation actions power desktop and a reachable phone tab bar.
const mobileMore = node("button", "Ещё", "nav-button mobile-more-nav");
mobileMore.id = "mobileMoreNav";
mobileMore.setAttribute("aria-haspopup", "dialog");
mobileMore.setAttribute("aria-label", "Ещё");
for(const [id,label] of [["createNav","Создать лист"],["savedNav","Моя библиотека"],["batchNav","Проверка работ"],["classesNav","Классы"]])$(id).setAttribute("aria-label",label);
mobileMore.prepend(studioIcon("M5 12h.01M12 12h.01M19 12h.01"));
document.querySelector(".topbar nav").append(mobileMore);
const mobileMenu = node("dialog", undefined, "mobile-menu");
mobileMenu.setAttribute("aria-labelledby", "mobileMenuTitle");
const mobileMenuHead = node("div", undefined, "mobile-menu-heading");
const mobileMenuTitle = node("h2", "Рабочее пространство"); mobileMenuTitle.id = "mobileMenuTitle";
const mobileMenuClose = node("button", "Закрыть", "button ghost");
mobileMenuClose.addEventListener("click", () => mobileMenu.close());
mobileMenuHead.append(mobileMenuTitle, mobileMenuClose); mobileMenu.append(mobileMenuHead);
for (const [id, title, hint] of [["scheduleNav", "Расписание", "Работы и печать к уроку"], ["analyticsNav", "Статистика", "Результаты и темы"], ["schoolNav", "Моя школа", "Учителя и отчёт завуча"], ["libraryNav", "Обмен материалами", "Листы других учителей"]]) {
  const button = node("button", undefined, "mobile-menu-item");
  button.append(node("strong", title), node("span", hint));
  button.addEventListener("click", () => { mobileMenu.close(); $(id).click(); });
  mobileMenu.append(button);
}
mobileMenu.addEventListener("click", e => { if (e.target === mobileMenu) mobileMenu.close(); });
document.body.append(mobileMenu);
mobileMore.addEventListener("click", () => mobileMenu.showModal());

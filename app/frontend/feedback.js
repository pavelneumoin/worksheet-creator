"use strict";
let feedbackStarsValue = 0;
function feedbackStars(value, interactive = false) {
  const wrap = node("span", undefined, interactive ? "feedback-stars" : "feedback-stars-readonly");
  for (let i = 1; i <= 5; i++) {
    const star = interactive ? node("button", "★", "feedback-star") : node("span", "★", "feedback-star");
    star.classList.toggle("selected", i <= value);
    if (interactive) {
      star.type = "button"; star.setAttribute("role", "radio"); star.setAttribute("aria-label", `${i} из 5 звёзд`);
      star.addEventListener("click", () => { feedbackStarsValue = i; document.querySelectorAll("#feedbackStars .feedback-star").forEach((s, index) => { s.classList.toggle("selected", index < i); s.setAttribute("aria-checked", String(index + 1 === i)); }); });
    }
    wrap.append(star);
  }
  return wrap;
}
function renderFeedback(data) {
  const summary = data.summary || {};
  $("feedbackAverage").textContent = summary.average ? `${summary.average.toFixed(1)} / 5` : "—";
  $("feedbackCount").textContent = summary.count ? `${summary.count} ${summary.count === 1 ? "отзыв" : "отзывов"}` : "Пока нет отзывов";
  $("feedbackRecommendSummary").textContent = summary.recommend_count ? `★ ${summary.recommend_count} рекомендуют коллегам` : "";
  const list = $("feedbackList"); list.replaceChildren();
  if (!data.feedback?.length) { list.append(node("p", "Здесь появятся первые впечатления учителей.", "quiet feedback-empty")); return; }
  for (const item of data.feedback) {
    const card = node("article", undefined, "feedback-card"), head = node("div", undefined, "feedback-card-head");
    head.append(node("strong", item.display_name || "Учитель"), node("time", new Date(item.updated_at).toLocaleDateString("ru-RU")));
    card.append(head, feedbackStars(item.stars));
    for (const [title, value, cls] of [["Понравилось", item.liked, "liked"], ["Неудобно", item.inconvenient, "inconvenient"], ["Что улучшить", item.improve, "improve"]]) {
      if (!value) continue; const block = node("div", undefined, `feedback-quote ${cls}`); block.append(node("span", title), node("p", value)); card.append(block);
    }
    if (item.recommend) card.append(node("span", "Рекомендует коллегам", "feedback-recommend"));
    list.append(card);
  }
}
function fillFeedbackForm(item) {
  feedbackStarsValue = item?.stars || 0; $("feedbackStars").replaceChildren(feedbackStars(feedbackStarsValue, true));
  $("feedbackDisplayName").value = item?.display_name || state.auth?.user?.first_name || "";
  $("feedbackLiked").value = item?.liked || ""; $("feedbackInconvenient").value = item?.inconvenient || ""; $("feedbackImprove").value = item?.improve || ""; $("feedbackRecommend").checked = !!item?.recommend;
  $("feedbackFormTitle").textContent = item ? "Обновить отзыв" : "Оставить отзыв";
}
async function refreshFeedback() { const data = await request("/api/v2/feedback"); renderFeedback(data); fillFeedbackForm(data.mine); }
$("feedbackNav").addEventListener("click", () => showView("feedback"));
$("feedbackForm").addEventListener("submit", (event) => { event.preventDefault(); busy("Сохраняем отзыв", async () => {
  if (!feedbackStarsValue) throw new Error("Поставьте оценку от 1 до 5 звёзд.");
  await request("/api/v2/feedback", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({stars:feedbackStarsValue,display_name:$("feedbackDisplayName").value,liked:$("feedbackLiked").value,inconvenient:$("feedbackInconvenient").value,improve:$("feedbackImprove").value,recommend:$("feedbackRecommend").checked})});
  $("feedbackStatus").textContent = "Спасибо! Отзыв сохранён."; await refreshFeedback();
}); });

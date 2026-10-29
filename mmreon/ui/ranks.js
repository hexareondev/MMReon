// Общие помощники для окна и виджета: медали, форматирование чисел.
const RANKS_URL = "https://www.opendota.com/assets/images/dota2/rank_icons/";
const HEROES_URL = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/";
const MEDAL_NAMES = ["Рекрут", "Страж", "Рыцарь", "Герой", "Легенда", "Властелин", "Божество", "Титан"];
const MEDAL_SHORT = ["Р", "С", "Ры", "Г", "Л", "В", "Б", "Т"];
const TIER_COLORS = ["#8FA27A", "#9AA7B6", "#6FB2C2", "#5E9BE0", "#D4B26E", "#4FC1B3", "#B596EA", "#E9895A"];
let medalIconsBroken = false;

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const sign = n => n > 0 ? "+" + n : n < 0 ? "−" + Math.abs(n) : "0";
const tone = n => n > 0 ? "win" : n < 0 ? "loss" : "muted";
const pad = n => String(n).padStart(2, "0");
const plural = (n, one, few, many) => {
  const m10 = n % 10, m100 = n % 100;
  return m10 === 1 && m100 !== 11 ? one : m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20) ? few : many;
};

function medalHTML(m, size) {
  const tier = TIER_COLORS[m.index] || "#C9A36A";
  const short = MEDAL_SHORT[m.index] + (m.stars || "");
  const fallback = `<div class="fallback" style="font-size:${Math.round(size / 3.4)}px">${short}</div>`;
  if (medalIconsBroken) {
    return `<div class="medal" style="width:${size}px;height:${size}px;--tier:${tier}" aria-hidden="true">${fallback}</div>`;
  }
  const n = m.index >= 7 ? 8 : m.index + 1;
  const star = m.stars && n < 8 ? `<img src="${RANKS_URL}rank_star_${m.stars}.png" alt="">` : "";
  return `<div class="medal" style="width:${size}px;height:${size}px;--tier:${tier}" aria-hidden="true">
    <img src="${RANKS_URL}rank_icon_${n}.png" alt="" onerror="medalIconFailed()">${star}</div>`;
}

// Без интернета иконки не грузятся — запоминаем и перерисовываем с запасным значком.
function medalIconFailed() {
  if (medalIconsBroken) return;
  medalIconsBroken = true;
  if (typeof onMedalIconsBroken === "function") onMedalIconsBroken();
}

"""Сборка данных для интерфейса: медаль, прогноз, сессия, график, герои, список матчей."""
from __future__ import annotations

import math
import statistics
import time
from datetime import datetime, timedelta

from . import heroes
from .tracker import is_double

MEDALS = ["Рекрут", "Страж", "Рыцарь", "Герой", "Легенда", "Властелин", "Божество"]
MEDAL_STEP = 770        # ширина медали в MMR
STAR_STEP = 154         # ширина звезды (у Божества чуть шире)
DIVINE_STAR = 160
IMMORTAL_FROM = 5420    # примерная граница, Valve её не публикует
SESSION_GAP = timedelta(hours=3)


def hero_name(code: str) -> str:
    return heroes.name(code)


def medal(rating: int | None) -> dict | None:
    if rating is None:
        return None
    if rating >= IMMORTAL_FROM:
        return {"name": "Титан", "stars": 0, "index": 7, "to_next": None, "next_name": None, "progress": 1.0,
                "to_medal": None, "next_medal": None}
    idx = min(rating // MEDAL_STEP, 6)
    floor = idx * MEDAL_STEP
    step = DIVINE_STAR if idx == 6 else STAR_STEP
    star = min(int((rating - floor) // step) + 1, 5)
    star_floor = floor + (star - 1) * step
    next_at = star_floor + step if star < 5 else (floor + MEDAL_STEP if idx < 6 else IMMORTAL_FROM)
    next_name = f"{MEDALS[idx]} {star + 1}" if star < 5 else (f"{MEDALS[idx + 1]} 1" if idx < 6 else "Титан")
    medal_at = floor + MEDAL_STEP if idx < 6 else IMMORTAL_FROM
    return {"name": f"{MEDALS[idx]} {star}", "stars": star, "index": idx,
            "to_next": max(next_at - rating, 0), "next_name": next_name,
            "progress": round((rating - star_floor) / (next_at - star_floor), 3),
            "to_medal": max(medal_at - rating, 0), "next_medal": MEDALS[idx + 1] if idx < 6 else "Титан"}


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def is_rated(m: dict) -> bool:
    """Рейтинговый матч: трекер видел изменение рейтинга или «История» подписала его рейтинговым."""
    if m["status"] in ("exact", "pending", "group"):
        return m.get("mode") in (None, "ranked")
    return m["status"] == "history" and m.get("mode") == "ranked"


def _estimate(m: dict, typical: float) -> int:
    mag = round(typical * (2 if is_double(m) else 1))
    if m.get("won") is None:
        return 0                     # итог ещё неизвестен (вышли до финального экрана)
    return mag if m["won"] else -mag


MODE_LABELS = {"ranked": "Рейтинговая", "turbo": "Turbo", "other": "Обычная"}


def _match_view(m: dict, typical: float) -> dict:
    status = m["status"]
    has_kda = m.get("kills") is not None
    view = {
        "id": m["match_id"],
        "ended_at": m["ended_at"],
        "started_at": m.get("started_at"),
        "hero": hero_name(m.get("hero")),
        "hero_code": m.get("hero") or "",
        "won": m["won"],
        "kda": f"{m.get('kills') or 0}/{m.get('deaths') or 0}/{m.get('assists') or 0}" if has_kda else None,
        "duration_sec": m.get("duration_sec"),
        "status": status,
        "mode": m.get("mode"),
        "mode_label": MODE_LABELS.get(m.get("mode")),
        "double": is_double(m),
        "double_manual": m.get("double_manual"),
        "delta": None, "estimate": None,
        "details": {k: m.get(k) for k in ("gpm", "xpm", "last_hits", "denies", "lh10", "level", "items",
                                          "backpack", "neutral", "item_timings", "scepter", "shard", "talents",
                                          "rating_before", "rating_after", "confidence")
                    if m.get(k) is not None},
    }
    if status == "exact":
        view["delta"] = m["delta"]
    elif status == "pending":
        view["estimate"] = _estimate(m, typical)
    elif status == "group":
        view["group_delta"] = m.get("group_delta")
    return view


def _session(matches: list) -> list:
    if not matches:
        return []
    last = _parse(matches[-1]["ended_at"])
    if datetime.now().astimezone() - last > SESSION_GAP:
        return []
    session = [matches[-1]]
    for m in reversed(matches[:-1]):
        if _parse(session[0]["ended_at"]) - _parse(m["ended_at"]) > SESSION_GAP:
            break
        session.insert(0, m)
    return session


def _win_gain(matches: list, typical: float) -> float:
    """Сколько обычно приносит одна победа без жетона — по последним точным матчам."""
    gains = [m["delta"] for m in matches if m["status"] == "exact" and m["delta"] > 0 and not is_double(m)][-20:]
    return statistics.median(gains) if len(gains) >= 3 else typical


def _forecast(med: dict | None, gain: float) -> dict | None:
    if not med or med.get("to_next") is None or gain <= 0:
        return None
    return {
        "per_win": round(gain),
        "wins_to_star": max(1, math.ceil(med["to_next"] / gain)),
        "wins_to_medal": max(1, math.ceil(med["to_medal"] / gain)) if med.get("to_medal") else None,
    }


def _when(m: dict) -> datetime:
    return _parse(m.get("started_at") or m["ended_at"])


def _bucket(stats: dict, key, m: dict):
    b = stats.setdefault(key, {"games": 0, "wins": 0, "mmr": 0, "mmr_games": 0})
    b["games"] += 1
    b["wins"] += 1 if m["won"] else 0
    if m["status"] == "exact":
        b["mmr"] += m["delta"]
        b["mmr_games"] += 1


def _finish(stats: dict, order: list, labels: dict) -> list:
    out = []
    for key in order:
        b = stats.get(key)
        if not b:
            continue
        out.append({"key": key, "label": labels[key], "games": b["games"], "wins": b["wins"],
                    "winrate": round(100 * b["wins"] / b["games"]),
                    "avg": round(b["mmr"] / b["mmr_games"], 1) if b["mmr_games"] else None})
    return out


def _patterns(matches: list) -> dict:
    """Закономерности: результат после серии поражений, по времени суток и по номеру матча в сессии."""
    rated = [m for m in matches if is_rated(m) and m.get("won") is not None]
    after, daytime, order = {}, {}, {}
    streak, index, prev_t = 0, 0, None
    for m in rated:
        t = _when(m)
        if prev_t is None or t - prev_t > SESSION_GAP:
            streak, index = 0, 0          # новая сессия: серия и счётчик обнуляются
        index += 1
        _bucket(after, min(streak, 3), m)
        _bucket(order, min(index, 5), m)
        h = t.astimezone().hour
        _bucket(daytime, "morning" if 6 <= h < 12 else "day" if 12 <= h < 18 else "evening" if h >= 18 else "night", m)
        streak = 0 if m["won"] else streak + 1
        prev_t = t
    return {
        "after_losses": _finish(after, [0, 1, 2, 3], {0: "После победы", 1: "После 1 поражения",
                                                      2: "После 2 поражений", 3: "После 3 и больше"}),
        "daytime": _finish(daytime, ["morning", "day", "evening", "night"],
                           {"morning": "Утро, 6–12", "day": "День, 12–18", "evening": "Вечер, 18–24", "night": "Ночь, 0–6"}),
        "order": _finish(order, [1, 2, 3, 4, 5], {1: "1-й матч", 2: "2-й", 3: "3-й", 4: "4-й", 5: "5-й и дальше"}),
        "total": len(rated),
    }


def _streak(session: list) -> dict | None:
    """Серия в конце текущей сессии: сколько побед или поражений подряд."""
    games = [m for m in session if m.get("won") is not None]
    if not games:
        return None
    last = games[-1]["won"]
    n = 0
    for m in reversed(games):
        if m["won"] != last:
            break
        n += 1
    return {"kind": "win" if last else "loss", "count": n}


def _item_medians(matches: list) -> dict:
    """{герой: {предмет: [время, …]}} по всем матчам с таймингами."""
    out: dict = {}
    for m in matches:
        for t in m.get("item_timings") or []:
            out.setdefault(m.get("hero"), {}).setdefault(t["item"], []).append((m["match_id"], t["t"]))
    return out


def _with_comparison(view: dict, m: dict, medians: dict) -> dict:
    """Добавляет к таймингам матча обычное время на этом герое (медиана других матчей, минимум 2)."""
    timings = view["details"].get("item_timings")
    if not timings:
        return view
    per_hero = medians.get(m.get("hero"), {})
    out = []
    for t in timings:
        others = [v for mid, v in per_hero.get(t["item"], []) if mid != m["match_id"]]
        row = dict(t)
        if len(others) >= 2:
            row["usual"] = round(statistics.median(others))
            row["samples"] = len(others)
        out.append(row)
    view["details"]["item_timings"] = out
    return view


def _goal(goal: dict | None, value: int | None, gain: float) -> dict | None:
    if not goal or value is None:
        return None
    target = int(goal["rating"])
    start = goal.get("start") or value
    left = target - value
    res = {"rating": target, "date": goal.get("date"), "start": start, "left": left, "reached": left <= 0,
           "medal": (medal(target) or {}).get("name")}
    span = target - start
    res["progress"] = 1.0 if left <= 0 else (max(0.0, min(1.0, (value - start) / span)) if span > 0 else 0.0)
    if left > 0 and gain > 0:
        res["wins"] = math.ceil(left / gain)
    if goal.get("date") and left > 0:
        try:
            end = datetime.fromisoformat(goal["date"]).date()
            days = (end - datetime.now().date()).days + 1
            res["days"] = days
            if days > 0 and res.get("wins"):
                res["per_day"] = round(res["wins"] / days, 1)
        except ValueError:
            pass
    return res


def _heroes(matches: list) -> list:
    stats = {}
    for m in matches:
        if not is_rated(m) or not m.get("hero") or m.get("won") is None:
            continue
        h = stats.setdefault(m["hero"], {"code": m["hero"], "name": hero_name(m["hero"]), "games": 0,
                                         "wins": 0, "mmr": 0, "mmr_games": 0, "last": m["ended_at"]})
        h["games"] += 1
        h["wins"] += 1 if m["won"] else 0
        h["last"] = max(h["last"], m["ended_at"])
        if m["status"] == "exact":
            h["mmr"] += m["delta"]
            h["mmr_games"] += 1
    result = []
    for h in stats.values():
        h["losses"] = h["games"] - h["wins"]
        h["winrate"] = round(100 * h["wins"] / h["games"])
        h["avg"] = round(h["mmr"] / h["mmr_games"], 1) if h["mmr_games"] else None
        result.append(h)
    result.sort(key=lambda h: (-h["games"], -h["wins"], h["name"]))
    return result


def build(tracker, dota_running: bool) -> dict:
    store = tracker.store
    with store.lock:
        matches = list(store.matches)
        rating = dict(store.rating) if store.rating else None
        history = list(store.data.get("history", []))
    typical = tracker.typical()
    value = rating["value"] if rating else None
    med = medal(value)

    session_all = _session(matches)
    session = [m for m in session_all if is_rated(m)]
    s_exact = sum(m["delta"] for m in session if m["status"] == "exact")
    groups = {}
    for m in session:
        if m["status"] == "group":
            groups[m.get("rating_after")] = m.get("group_delta") or 0
    s_exact += sum(groups.values())
    pending = [m for m in session if m["status"] == "pending"]
    s_est = sum(_estimate(m, typical) for m in pending)

    now = datetime.now().astimezone()
    week_ago = now - timedelta(days=7)
    before_week = [h for h in history if _parse(h["at"]) <= week_ago]
    week_base = (before_week[-1] if before_week else (history[0] if history else None))
    week_matches = [m for m in matches if _parse(m["ended_at"]) >= week_ago and is_rated(m) and m.get("won") is not None]
    week_wins = sum(1 for m in week_matches if m["won"])

    month_ago = now - timedelta(days=30)
    chart = [h for h in history if _parse(h["at"]) >= month_ago]
    prior = [h for h in history if _parse(h["at"]) < month_ago]
    if prior:
        chart.insert(0, {"value": prior[-1]["value"], "at": month_ago.isoformat(timespec="seconds")})

    gain = _win_gain(matches, typical)
    medians = _item_medians(matches)
    gsi_age = None if tracker.last_gsi_at is None else time.time() - tracker.last_gsi_at
    return {
        "rating": rating,
        "medal": med,
        "forecast": _forecast(med, gain),
        "goal": _goal(tracker.cfg.get("goal"), value, gain),
        "streak": _streak(session),
        "patterns": _patterns(matches),
        "session": {
            "wins": sum(1 for m in session if m["won"]),
            "losses": sum(1 for m in session if m["won"] is False),
            "delta": s_exact,
            "estimate": s_est,
            "pending": len(pending),
            "doubles": sum(1 for m in session if is_double(m)),
            "items": [_match_view(m, typical) for m in session_all],
            "started_at": (session_all or [{}])[0].get("ended_at"),
        },
        "last_hero": next((m.get("hero") for m in reversed(matches) if m.get("hero")), None),
        "week": {
            "delta": (value - week_base["value"]) if (value is not None and week_base) else None,
            "matches": len(week_matches),
            "winrate": round(100 * week_wins / len(week_matches)) if week_matches else None,
        },
        "chart": chart,
        "heroes": _heroes(matches),
        "matches": [_with_comparison(_match_view(m, typical), m, medians) for m in reversed(matches[-400:])],
        "status": {
            "gsi": gsi_age is not None and gsi_age < 90,
            "dota_running": dota_running,
            "in_match": tracker.in_match,
            "waiting_history": bool(store.pending()) or rating is None,
            "has_rating": rating is not None,
        },
    }

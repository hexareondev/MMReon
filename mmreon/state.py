"""Сборка данных для интерфейса: медаль, сессия, график, список матчей."""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from .tracker import is_double

MEDALS = ["Рекрут", "Страж", "Рыцарь", "Герой", "Легенда", "Властелин", "Божество"]
MEDAL_STEP = 770        # ширина медали в MMR
STAR_STEP = 154         # ширина звезды (у Божества чуть шире)
DIVINE_STAR = 160
IMMORTAL_FROM = 5420    # примерная граница, Valve её не публикует
SESSION_GAP = timedelta(hours=3)

HERO_NAMES = {
    "antimage": "Anti-Mage", "nevermore": "Shadow Fiend", "obsidian_destroyer": "Outworld Destroyer",
    "wisp": "Io", "skeleton_king": "Wraith King", "windrunner": "Windranger", "zuus": "Zeus",
    "rattletrap": "Clockwerk", "furion": "Nature's Prophet", "magnataur": "Magnus",
    "doom_bringer": "Doom", "queenofpain": "Queen of Pain", "life_stealer": "Lifestealer",
    "shredder": "Timbersaw", "abyssal_underlord": "Underlord", "treant": "Treant Protector",
    "vengefulspirit": "Vengeful Spirit", "necrolyte": "Necrophos", "centaur": "Centaur Warrunner",
    "keeper_of_the_light": "Keeper of the Light", "drow_ranger": "Drow Ranger",
}


def hero_name(code: str) -> str:
    if not code:
        return "Неизвестный герой"
    return HERO_NAMES.get(code) or code.replace("_", " ").title()


def medal(rating: int | None) -> dict | None:
    if rating is None:
        return None
    if rating >= IMMORTAL_FROM:
        return {"name": "Титан", "stars": 0, "index": 7, "to_next": None, "next_name": None, "progress": 1.0}
    idx = min(rating // MEDAL_STEP, 6)
    floor = idx * MEDAL_STEP
    step = DIVINE_STAR if idx == 6 else STAR_STEP
    star = min(int((rating - floor) // step) + 1, 5)
    star_floor = floor + (star - 1) * step
    next_at = star_floor + step if star < 5 else (floor + MEDAL_STEP if idx < 6 else IMMORTAL_FROM)
    next_name = f"{MEDALS[idx]} {star + 1}" if star < 5 else (f"{MEDALS[idx + 1]} 1" if idx < 6 else "Титан")
    return {"name": f"{MEDALS[idx]} {star}", "stars": star, "index": idx,
            "to_next": max(next_at - rating, 0), "next_name": next_name,
            "progress": round((rating - star_floor) / (next_at - star_floor), 3)}


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _estimate(m: dict, typical: float) -> int:
    mag = round(typical * (2 if is_double(m) else 1))
    return mag if m["won"] else -mag


def _match_view(m: dict, typical: float) -> dict:
    status = m["status"]
    view = {
        "id": m["match_id"],
        "ended_at": m["ended_at"],
        "hero": hero_name(m.get("hero")),
        "hero_code": m.get("hero") or "",
        "won": m["won"],
        "kda": f"{m.get('kills') or 0}/{m.get('deaths') or 0}/{m.get('assists') or 0}",
        "duration_sec": m.get("duration_sec"),
        "gpm": m.get("gpm"), "xpm": m.get("xpm"),
        "status": status,
        "double": is_double(m),
        "double_manual": m.get("double_manual"),
        "delta": None, "estimate": None,
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


def build(tracker, dota_running: bool) -> dict:
    store = tracker.store
    with store.lock:
        matches = list(store.matches)
        rating = dict(store.rating) if store.rating else None
        history = list(store.data.get("history", []))
    typical = tracker.typical()
    value = rating["value"] if rating else None

    session = [m for m in _session(matches) if m["status"] != "unrated"]
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
    week_matches = [m for m in matches if _parse(m["ended_at"]) >= week_ago and m["status"] != "unrated"]
    week_wins = sum(1 for m in week_matches if m["won"])

    month_ago = now - timedelta(days=30)
    chart = [h for h in history if _parse(h["at"]) >= month_ago]
    prior = [h for h in history if _parse(h["at"]) < month_ago]
    if prior:
        chart.insert(0, {"value": prior[-1]["value"], "at": month_ago.isoformat(timespec="seconds")})

    gsi_age = None if tracker.last_gsi_at is None else time.time() - tracker.last_gsi_at
    return {
        "rating": rating,
        "medal": medal(value),
        "session": {
            "wins": sum(1 for m in session if m["won"]),
            "losses": sum(1 for m in session if not m["won"]),
            "delta": s_exact,
            "estimate": s_est,
            "pending": len(pending),
            "doubles": sum(1 for m in session if is_double(m)),
            "items": [_match_view(m, typical) for m in _session(matches)],
            "started_at": (_session(matches) or [{}])[0].get("ended_at"),
        },
        "last_hero": next((m.get("hero") for m in reversed(matches) if m.get("hero")), None),
        "week": {
            "delta": (value - week_base["value"]) if (value is not None and week_base) else None,
            "matches": len(week_matches),
            "winrate": round(100 * week_wins / len(week_matches)) if week_matches else None,
        },
        "chart": chart,
        "matches": [_match_view(m, typical) for m in reversed(matches[-50:])],
        "status": {
            "gsi": gsi_age is not None and gsi_age < 90,
            "dota_running": dota_running,
            "in_match": tracker.in_match,
            "waiting_history": bool(store.pending()) or rating is None,
            "has_rating": rating is not None,
        },
    }

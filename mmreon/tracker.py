"""Логика трекера: конец матча из GSI → ожидание вкладки «История» → точное изменение рейтинга."""
from __future__ import annotations

import statistics
import threading
import time
from datetime import datetime, timedelta

from . import ocr
from .store import Store

POST_GAME = "DOTA_GAMERULES_STATE_POST_GAME"
TYPICAL_DELTA = 28          # пока нет своей статистики
DOUBLE_FACTOR = 1.6         # изменение в 1.6+ раза больше обычного — похоже на жетон ×2
IDLE_SCAN_SEC = 5.0         # когда ничего не ждём, «Историю» проверяем реже — только для сверки таблицы
HISTORY_MATCH_WINDOW = timedelta(minutes=20)

# Расходники и мелочь — их время покупки не показываем.
CONSUMABLES = {
    "tango", "flask", "clarity", "enchanted_mango", "faerie_fire", "ward_observer", "ward_sentry",
    "ward_dispenser", "dust", "smoke_of_deceit", "tpscroll", "tome_of_knowledge", "blood_grenade",
    "branches", "famango", "great_famango", "greater_famango", "cheese", "aegis", "refresher_shard",
    "royal_jelly", "roshans_banner", "bottle",
}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _local_naive(iso: str) -> datetime:
    return datetime.fromisoformat(iso).astimezone().replace(tzinfo=None)


def _same_match(m: dict, hero, won, duration, ended_est: datetime) -> bool:
    """Тот же матч: герой, результат и длительность до 3 секунд, в пределах суток."""
    if not hero or m.get("hero") != hero:
        return False
    if m.get("won") is not None and won is not None and m.get("won") != won:
        return False
    if duration is None or m.get("duration_sec") is None or abs(m["duration_sec"] - duration) > 3:
        return False
    return abs(_local_naive(m["ended_at"]) - ended_est) <= timedelta(days=1)


def _ordered_rows(rows: list) -> list:
    """Таблица «Истории» идёт от новых матчей к старым. Строки, чьё время ломает этот порядок,
    прочитаны с ошибкой — оставляем самую длинную непротиворечивую последовательность."""
    n = len(rows)
    if n < 3:
        return rows
    best = [1] * n
    prev = [-1] * n
    for i in range(n):
        for j in range(i):
            if rows[j]["started"] >= rows[i]["started"] and best[j] + 1 > best[i]:
                best[i], prev[i] = best[j] + 1, j
    i = max(range(n), key=lambda k: best[k])
    keep = set()
    while i != -1:
        keep.add(i)
        i = prev[i]
    return [r for k, r in enumerate(rows) if k in keep]


def _items(payload: dict) -> dict:
    """Предметы из раздела items GSI: инвентарь, рюкзак, тайник, нейтральный."""
    raw = payload.get("items") or {}

    def name(slot):
        n = (raw.get(slot) or {}).get("name") or "empty"
        return None if n == "empty" else n.replace("item_", "")

    return {
        "inventory": [name(f"slot{i}") for i in range(6)],
        "backpack": [name(f"slot{i}") for i in range(6, 9)],
        "stash": [name(f"stash{i}") for i in range(6)],
        "neutral": name("neutral0"),
    }


def is_double(m: dict) -> bool:
    """Жетон ×2: ручная отметка важнее автоматической."""
    manual = m.get("double_manual")
    return bool(m.get("double")) if manual is None else manual


def _fmt(delta: int) -> str:
    return f"+{delta}" if delta > 0 else str(delta)


class Tracker:
    def __init__(self, store: Store, grab_frame, cfg: dict, log=print):
        self.store = store
        self.grab_frame = grab_frame    # функция без аргументов → кадр BGR или None
        self.cfg = cfg
        self.log = log
        self.on_rated = None            # вызывается, когда изменение рейтинга записано: (матч, было, стало)
        self.in_match = False
        self.last_gsi_at = None         # time.time() последнего пакета от Доты
        self._candidate = None          # прошлое прочтение, ждём подтверждения вторым кадром
        self._black_count = 0
        self._warned_black = False
        self._sig_seen = None           # отпечаток таблицы «Истории» на прошлом кадре
        self._sig_synced = None         # отпечаток, который уже сверен с журналом
        self._live = None               # данные текущего матча: тайминги предметов, добивания к 10:00
        self._stop = threading.Event()

    # ---------- GSI ----------

    def _track_live(self, match_id: str, payload: dict):
        """Во время матча запоминаем, когда впервые появился каждый предмет, и добивания к 10:00."""
        if not self._live or self._live["match_id"] != match_id:
            self._live = {"match_id": match_id, "first_seen": {}, "lh10": None, "items": None, "hero": None}
        live = self._live
        clock = (payload.get("map") or {}).get("clock_time")
        if payload.get("items"):
            items = _items(payload)
            live["items"] = items
            if clock is not None:
                for n in items["inventory"] + items["backpack"] + items["stash"] + [items["neutral"]]:
                    if n and n not in live["first_seen"]:
                        live["first_seen"][n] = clock
        if payload.get("hero"):
            live["hero"] = payload["hero"]
        if payload.get("player"):
            live["player"] = payload["player"]
        game = payload.get("map") or {}
        live["map"] = game
        if game.get("win_team") in ("radiant", "dire"):
            live["win_team"] = game["win_team"]      # трон уже пал, финальный экран ещё не показан
        lh = (payload.get("player") or {}).get("last_hits")
        if live["lh10"] is None and clock is not None and clock >= 600 and lh is not None:
            live["lh10"] = lh

    def _build_details(self, match_id: str, payload: dict) -> dict:
        live = self._live if self._live and self._live["match_id"] == match_id else None
        items = _items(payload) if payload.get("items") else (live or {}).get("items")
        hero = payload.get("hero") or (live or {}).get("hero") or {}
        details = {}
        if items:
            details["items"] = items["inventory"]
            details["backpack"] = items["backpack"]
            details["neutral"] = items["neutral"]
        if live:
            timings = [{"item": n, "t": t} for n, t in live["first_seen"].items()
                       if n not in CONSUMABLES and not n.startswith("recipe_") and t is not None and t > 0]
            details["item_timings"] = sorted(timings, key=lambda x: x["t"])
            details["lh10"] = live["lh10"]
        if "aghanims_scepter" in hero or "aghanims_shard" in hero:
            details["scepter"] = bool(hero.get("aghanims_scepter"))
            details["shard"] = bool(hero.get("aghanims_shard"))
        talents = [bool(hero.get(f"talent_{i}")) for i in range(1, 9)]
        if any(f"talent_{i}" in hero for i in range(1, 9)):
            details["talents"] = talents
        if "level" in hero:
            details["level"] = hero.get("level")
        return details

    def on_gsi(self, payload: dict):
        if self.last_gsi_at is None:
            self.log("[GSI] связь с Дотой есть")
        self.last_gsi_at = time.time()
        game = payload.get("map")
        if not game:
            self.in_match = False       # главное меню: в пакете нет раздела map
            self._finish_left_match()
            return
        state = game.get("game_state", "")
        match_id = str(game.get("matchid") or "0")
        if match_id == "0" or game.get("customgamename"):
            self.in_match = state != POST_GAME
            return
        if state != POST_GAME:
            self.in_match = True
            self._track_live(match_id, payload)
            return
        self.in_match = False
        win_team = game.get("win_team")
        if win_team not in ("radiant", "dire"):
            return
        player = payload.get("player", {})
        won = player.get("team_name") == win_team
        with self.store.lock:
            existing = self.store.find(match_id)
            if existing and not existing.get("partial"):
                return
            if existing:
                # Матч уже записан при выходе в лобби (например, после переподключения) — дополняем.
                fresh = self._match_record(match_id, payload, won)
                for k, v in fresh.items():
                    if k not in ("status", "delta", "rating_before", "rating_after", "confidence", "double",
                                 "mode", "ended_at", "history_key", "started_at") and v is not None:
                        existing[k] = v
                existing.pop("partial", None)
                match = existing
            else:
                match = self._match_record(match_id, payload, won)
                self.store.matches.append(match)
            self.store.save()
        self._live = None
        result = "Победа" if match["won"] else "Поражение"
        self.log(f"[матч] {match_id}: {result}, {match['hero']} "
                 f"{match['kills']}/{match['deaths']}/{match['assists']} — "
                 f"откройте «Профиль → История», чтобы записать точный рейтинг")

    def _match_record(self, match_id: str, payload: dict, won) -> dict:
        player = payload.get("player") or {}
        hero = payload.get("hero") or {}
        game = payload.get("map") or {}
        match = {
            "match_id": match_id,
            "ended_at": _now(),
            "hero": (hero.get("name") or "").replace("npc_dota_hero_", ""),
            "won": won,
            "kills": player.get("kills"),
            "deaths": player.get("deaths"),
            "assists": player.get("assists"),
            "last_hits": player.get("last_hits"),
            "denies": player.get("denies"),
            "gpm": player.get("gold_per_minute"),
            "xpm": player.get("xp_per_minute"),
            "duration_sec": game.get("clock_time"),
            "status": "pending",
            "delta": None,
            "rating_before": None,
            "rating_after": None,
            "confidence": None,
            "double": None,
            "mode": None,
        }
        match.update(self._build_details(match_id, payload))
        return match

    def _finish_left_match(self):
        """Вышли в лобби, не дождавшись финального экрана: записываем матч из данных, собранных по ходу игры.
        Результат известен, если трон уже пал; иначе его подскажет изменение рейтинга или «История»."""
        live, self._live = self._live, None
        if not live or not live.get("player") or not live.get("hero"):
            return
        game = live.get("map") or {}
        if (game.get("clock_time") or 0) <= 0:
            return                      # игра не началась (вышли на драфте) — матча нет
        match_id = live["match_id"]
        player = live["player"]
        won = player.get("team_name") == live["win_team"] if live.get("win_team") else None
        payload = {"player": player, "hero": live["hero"], "map": game}
        self._live = live               # нужен _build_details для предметов и таймингов
        try:
            with self.store.lock:
                if self.store.find(match_id):
                    return
                match = self._match_record(match_id, payload, won)
                match["partial"] = True     # если Дота всё же пришлёт финальный экран — дополним
                self.store.matches.append(match)
                self.store.save()
        finally:
            self._live = None
        result = {True: "победа", False: "поражение", None: "итог пока неизвестен"}[won]
        self.log(f"[матч] {match_id}: вышли до финального экрана, {result}, {match['hero']} "
                 f"{match['kills']}/{match['deaths']}/{match['assists']}")

    # ---------- распознавание ----------

    def needs_rating(self) -> bool:
        return self.store.rating is None or bool(self.store.pending())

    def needs_scan(self) -> bool:
        return not self.in_match

    def scan_once(self) -> dict | None:
        frame = self.grab_frame()
        if frame is None:
            return None
        if frame.mean() < 3.0:
            # Одиночный чёрный кадр бывает при переключении окон — предупреждаем, только если он держится.
            self._black_count += 1
            if self._black_count >= 5 and not self._warned_black:
                self.log("[экран] кадр чёрный — переключите Доту в режим «Оконный без рамки»")
                self._warned_black = True
            return None
        self._black_count = 0
        loc = ocr.locate(frame)
        if not loc:
            self._candidate = None
            self._sig_seen = None
            return None
        frame, anchor = loc

        # Таблицу сверяем, когда она изменилась и не меняется два кадра подряд (дорисовалась).
        sig = ocr.table_signature(frame, anchor)
        if sig == self._sig_seen and sig != self._sig_synced:
            try:
                self.sync_history(ocr.read_history(frame, anchor))
            finally:
                self._sig_synced = sig
        self._sig_seen = sig

        if not self.needs_rating():
            return None
        reading = ocr.read_rating(frame, anchor)
        if not reading:
            self._candidate = None
            return None
        # Принимаем цифру, только если два кадра подряд дали одно и то же.
        key = (reading["rating"], reading["confidence"])
        if self._candidate != key:
            self._candidate = key
            return None
        self._candidate = None
        self.accept(reading["rating"], reading["confidence"])
        return reading

    # ---------- сверка с таблицей «Истории» ----------

    def sync_history(self, rows: list) -> None:
        """Тип игры для записанных матчей и матчи, сыгранные без трекера."""
        if not rows:
            return
        rows = _ordered_rows(rows)
        added = typed = 0
        with self.store.lock:
            matches = self.store.matches
            removed = self._dedupe_history()
            for row in rows:
                if row["won"] is None:
                    continue
                started = row["started"]
                ended_est = started + timedelta(seconds=row["duration_sec"] or 0)
                key = f"h-{started:%Y%m%d%H%M}-{row['hero']}"

                # Свой матч: тот же герой и время окончания рядом с расчётным.
                best, best_gap = None, None
                for m in matches:
                    if m.get("hero") != row["hero"] or m.get("history_key") not in (None, key):
                        continue
                    gap = abs(_local_naive(m["ended_at"]) - ended_est)
                    if gap <= HISTORY_MATCH_WINDOW and (best_gap is None or gap < best_gap):
                        best, best_gap = m, gap
                if best is not None:
                    changed = best.get("history_key") != key or best.get("mode") != row["mode"]
                    best["history_key"] = key
                    best["mode"] = row["mode"]
                    if best.get("won") is None:
                        best["won"] = row["won"]
                        changed = True
                    best.setdefault("started_at", started.astimezone().isoformat(timespec="seconds"))
                    if best["status"] == "pending" and row["mode"] == "turbo":
                        best["status"] = "unrated"     # турбо рейтинг не меняет — не ждём цифру
                    typed += changed
                    continue

                # Время могло прочитаться с ошибкой (например, на подсвеченной курсором строке),
                # но герой, результат и длительность до секунды совпадают — это тот же матч.
                twin = next((m for m in matches if _same_match(m, row["hero"], row["won"], row["duration_sec"], ended_est)), None)
                if twin is not None:
                    if not twin.get("history_key"):
                        twin["history_key"] = key
                        twin["mode"] = row["mode"]
                        typed += 1
                    continue

                # Матч, которого нет в журнале: трекер был выключен или это игра до установки.
                matches.append({
                    "match_id": key,
                    "history_key": key,
                    "source": "history",
                    "started_at": started.astimezone().isoformat(timespec="seconds"),
                    "ended_at": ended_est.astimezone().isoformat(timespec="seconds"),
                    "hero": row["hero"],
                    "won": row["won"],
                    "duration_sec": row["duration_sec"],
                    "mode": row["mode"],
                    "status": "history",
                    "delta": None,
                })
                added += 1
            if added or typed or removed:
                matches.sort(key=lambda m: _local_naive(m["ended_at"]))
                self.store.save()
        if added:
            self.log(f"[история] добавлено матчей из «Истории»: {added}")

    def _dedupe_history(self) -> int:
        """Убирает матчи «из Истории», которые дублируют уже записанный матч
        (так бывало, когда время в таблице прочиталось с ошибкой)."""
        matches = self.store.matches
        drop = []
        for i, m in enumerate(matches):
            if m.get("source") != "history":
                continue
            for j, other in enumerate(matches):
                if i == j or j in drop:
                    continue
                # Сохраняем записанный трекером матч; из двух дублей «из Истории» — более ранний в списке.
                if other.get("source") == "history" and j > i:
                    continue
                if _same_match(other, m.get("hero"), m.get("won"), m.get("duration_sec"), _local_naive(m["ended_at"])):
                    drop.append(i)
                    break
        for i in reversed(drop):
            del matches[i]
        if drop:
            self.log(f"[история] убраны дубли матчей: {len(drop)}")
        return len(drop)

    def cleanup(self):
        """Однократная чистка журнала при запуске."""
        with self.store.lock:
            if self._dedupe_history():
                self.store.save()

    def accept(self, rating: int, confidence: int | None):
        with self.store.lock:
            prev = self.store.rating
            pending = self.store.pending()
            new_state = {"value": rating, "confidence": confidence, "read_at": _now()}
            history = self.store.data.setdefault("history", [])
            if not history or history[-1]["value"] != rating:
                history.append({"value": rating, "at": new_state["read_at"]})

            if prev is None:
                self.store.rating = new_state
                self.store.save()
                self.log(f"[рейтинг] исходная точка: {rating}" + self._conf(confidence))
                return

            delta = rating - prev["value"]

            if not pending:
                if delta != 0:
                    self.log(f"[рейтинг] {prev['value']} → {rating} ({_fmt(delta)}) без записанного матча "
                             f"— видимо, трекер не был запущен")
                self.store.rating = new_state
                self.store.save()
                return

            if len(pending) == 1:
                m = pending[0]
                if delta == 0:
                    m["status"] = "unrated"
                    self.log(f"[рейтинг] {m['match_id']}: рейтинг не изменился — нерейтинговая игра")
                elif abs(delta) > self.cfg["max_delta"] or (m["won"] is not None and (delta > 0) != m["won"]):
                    if history and history[-1]["value"] == rating:
                        history.pop()
                    self.log(f"[рейтинг] прочитано {rating}, изменение {_fmt(delta)} не сходится "
                             f"с результатом матча — не записываю, проверю ещё раз")
                    return
                else:
                    if m["won"] is None:
                        m["won"] = delta > 0       # итог не дошёл из Доты — рейтинг его однозначно показывает
                    self._fill(m, prev["value"], rating, confidence)
                    self.log(f"[рейтинг] {m['match_id']}: {prev['value']} → {rating} — ИР {_fmt(delta)}"
                             + (" (похоже на жетон ×2)" if m["double"] else "") + self._conf(confidence))
            else:
                # Несколько матчей без промежуточного чтения: знаем только сумму.
                for m in pending:
                    m["status"] = "group"
                    m["rating_after"] = rating
                    m["group_delta"] = delta
                self.log(f"[рейтинг] {len(pending)} матча подряд без открытия «Истории»: "
                         f"суммарно {_fmt(delta)}, по матчам разложить нельзя")

            self.store.rating = new_state
            self.store.save()
            rated = pending[-1]
        if self.on_rated:
            try:
                self.on_rated(rated, prev["value"], rating)
            except Exception as exc:
                self.log(f"[уведомление] ошибка: {exc!r}")

    def _fill(self, m, before, after, confidence):
        delta = after - before
        m.update(status="exact", delta=delta, rating_before=before, rating_after=after,
                 confidence=confidence, double=abs(delta) >= self._typical() * DOUBLE_FACTOR)

    def toggle_double(self, match_id: str) -> bool | None:
        """Ручная отметка жетона ×2: авто → да → нет → авто."""
        with self.store.lock:
            m = self.store.find(match_id)
            if not m:
                return None
            cur = m.get("double_manual")
            m["double_manual"] = True if cur is None else (False if cur else None)
            self.store.save()
            return m["double_manual"]

    def typical(self) -> float:
        return self._typical()

    def _typical(self) -> float:
        recent = [abs(m["delta"]) for m in self.store.matches
                  if m["status"] == "exact" and not is_double(m)][-30:]
        return statistics.median(recent) if len(recent) >= 5 else TYPICAL_DELTA

    @staticmethod
    def _conf(confidence):
        return f", уверенность {confidence}%" if confidence is not None else ""

    # ---------- цикл ----------

    def run_scanner(self):
        fast = float(self.cfg["scan_interval_sec"])
        while not self._stop.is_set():
            if self.needs_scan():
                try:
                    self.scan_once()
                except Exception as exc:
                    self.log(f"[экран] ошибка: {exc!r}")
            # Ждём цифру — смотрим часто; иначе только сверяем таблицу, реже.
            self._stop.wait(fast if self.needs_rating() or self._sig_seen != self._sig_synced else IDLE_SCAN_SEC)

    def stop(self):
        self._stop.set()

    def summary(self) -> str:
        rated = [m for m in self.store.matches if m["status"] == "exact"]
        r = self.store.rating
        head = f"Рейтинг: {r['value']}" if r else "Рейтинг ещё не прочитан"
        return f"{head}, матчей в журнале: {len(self.store.matches)}, с точным ИР: {len(rated)}"

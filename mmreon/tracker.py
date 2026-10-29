"""Логика трекера: конец матча из GSI → ожидание вкладки «История» → точное изменение рейтинга."""
from __future__ import annotations

import statistics
import threading
import time
from datetime import datetime

from . import ocr
from .store import Store

POST_GAME = "DOTA_GAMERULES_STATE_POST_GAME"
TYPICAL_DELTA = 28          # пока нет своей статистики
DOUBLE_FACTOR = 1.6         # изменение в 1.6+ раза больше обычного — похоже на жетон ×2


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _fmt(delta: int) -> str:
    return f"+{delta}" if delta > 0 else str(delta)


class Tracker:
    def __init__(self, store: Store, grab_frame, cfg: dict, log=print):
        self.store = store
        self.grab_frame = grab_frame    # функция без аргументов → кадр BGR или None
        self.cfg = cfg
        self.log = log
        self.in_match = False
        self._candidate = None          # прошлое прочтение, ждём подтверждения вторым кадром
        self._warned_black = False
        self._stop = threading.Event()

    # ---------- GSI ----------

    def on_gsi(self, payload: dict):
        game = payload.get("map")
        if not game:
            self.in_match = False       # главное меню: в пакете нет раздела map
            return
        state = game.get("game_state", "")
        match_id = str(game.get("matchid") or "0")
        if match_id == "0" or game.get("customgamename"):
            self.in_match = state != POST_GAME
            return
        if state != POST_GAME:
            self.in_match = True
            return
        self.in_match = False
        win_team = game.get("win_team")
        if win_team not in ("radiant", "dire"):
            return
        with self.store.lock:
            if self.store.find(match_id):
                return
            player = payload.get("player", {})
            hero = payload.get("hero", {})
            match = {
                "match_id": match_id,
                "ended_at": _now(),
                "hero": (hero.get("name") or "").replace("npc_dota_hero_", ""),
                "won": player.get("team_name") == win_team,
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
            }
            self.store.matches.append(match)
            self.store.save()
        result = "Победа" if match["won"] else "Поражение"
        self.log(f"[матч] {match_id}: {result}, {match['hero']} "
                 f"{match['kills']}/{match['deaths']}/{match['assists']} — "
                 f"откройте «Профиль → История», чтобы записать точный рейтинг")

    # ---------- распознавание ----------

    def needs_scan(self) -> bool:
        return not self.in_match and (self.store.rating is None or bool(self.store.pending()))

    def scan_once(self) -> dict | None:
        frame = self.grab_frame()
        if frame is None:
            return None
        if frame.mean() < 3.0:
            if not self._warned_black:
                self.log("[экран] кадр чёрный — переключите Доту в режим «Оконный без рамки»")
                self._warned_black = True
            return None
        reading = ocr.read(frame)
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

    def accept(self, rating: int, confidence: int | None):
        with self.store.lock:
            prev = self.store.rating
            pending = self.store.pending()
            new_state = {"value": rating, "confidence": confidence, "read_at": _now()}

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
                elif abs(delta) > self.cfg["max_delta"] or (delta > 0) != m["won"]:
                    self.log(f"[рейтинг] прочитано {rating}, изменение {_fmt(delta)} не сходится "
                             f"с результатом матча — не записываю, проверю ещё раз")
                    return
                else:
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

    def _fill(self, m, before, after, confidence):
        delta = after - before
        m.update(status="exact", delta=delta, rating_before=before, rating_after=after,
                 confidence=confidence, double=abs(delta) >= self._typical() * DOUBLE_FACTOR)

    def _typical(self) -> float:
        recent = [abs(m["delta"]) for m in self.store.matches
                  if m["status"] == "exact" and not m.get("double")][-30:]
        return statistics.median(recent) if len(recent) >= 5 else TYPICAL_DELTA

    @staticmethod
    def _conf(confidence):
        return f", уверенность {confidence}%" if confidence is not None else ""

    # ---------- цикл ----------

    def run_scanner(self):
        interval = float(self.cfg["scan_interval_sec"])
        while not self._stop.is_set():
            if self.needs_scan():
                try:
                    self.scan_once()
                except Exception as exc:
                    self.log(f"[экран] ошибка: {exc!r}")
            self._stop.wait(interval)

    def stop(self):
        self._stop.set()

    def summary(self) -> str:
        rated = [m for m in self.store.matches if m["status"] == "exact"]
        r = self.store.rating
        head = f"Рейтинг: {r['value']}" if r else "Рейтинг ещё не прочитан"
        return f"{head} · матчей записано: {len(self.store.matches)} · с точным ИР: {len(rated)}"

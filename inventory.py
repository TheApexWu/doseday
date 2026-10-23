"""Weekly schedule (slot -> pill type -> count) and a log of what the arm actually placed.

The log is append-only JSONL so a crash mid-fill leaves an exact record of which slots are done,
and a caregiver can check every placement against its photo.
"""
import json
import time
from collections import Counter
from pathlib import Path

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
SLOTS = tuple(f"{d}-{t}" for d in DAYS for t in ("AM", "PM"))


class OverfillError(RuntimeError):
    pass


class Inventory:
    def __init__(self, schedule: dict[str, dict[str, int]], log_path=None, stock: dict | None = None):
        unknown = set(schedule) - set(SLOTS)
        if unknown:
            raise ValueError(f"unknown slots {sorted(unknown)}; use e.g. Mon-AM")
        self.schedule = {s: dict(schedule[s]) for s in SLOTS if s in schedule}
        self.placed: Counter = Counter()      # (slot, type) -> count
        self.events: list[dict] = []
        self.stock = Counter(stock or {})     # pills on hand per type, for refill alerts
        self.log_path = Path(log_path) if log_path else None
        if self.log_path and self.log_path.exists():
            for line in self.log_path.read_text().splitlines():
                self._apply(json.loads(line))

    @classmethod
    def from_json(cls, path, log_path=None) -> "Inventory":
        d = json.loads(Path(path).read_text())
        return cls(d["schedule"], log_path=log_path, stock=d.get("stock"))

    def need(self, slot: str, kind: str) -> int:
        return self.schedule.get(slot, {}).get(kind, 0) - self.placed[(slot, kind)]

    def next_slot(self, kind: str) -> str | None:
        """Earliest slot in the week still missing this type; None means this pill is surplus."""
        return next((s for s in self.schedule if self.need(s, kind) > 0), None)

    def _apply(self, e: dict) -> None:
        """Replay one logged event. Stock changes are stored on the event, so reload matches the run."""
        key = (e["slot"], e["type"])
        if e["event"] == "placed":
            self.placed[key] += 1
            if e.get("from_stock"):
                self.stock[e["type"]] -= 1
        elif e["event"] == "retracted":
            self.placed[key] -= 1
            if e.get("restored"):
                self.stock[e["type"]] += 1
        self.events.append(e)

    def _commit(self, e: dict) -> dict:
        self._apply(e)
        if self.log_path:
            with self.log_path.open("a") as f:
                f.write(json.dumps(e) + "\n")
        return e

    def _open_placement(self, slot: str, kind: str) -> dict | None:
        """Newest placement for this slot and type that no later retraction has undone."""
        undone = 0
        for e in reversed(self.events):
            if (e["slot"], e["type"]) != (slot, kind):
                continue
            if e["event"] == "retracted":
                undone += 1
            elif undone:
                undone -= 1
            else:
                return e
        return None

    def record(self, slot: str, kind: str, **extra) -> dict:
        if self.need(slot, kind) <= 0:
            raise OverfillError(f"{slot} already has its {kind}")
        e = {"event": "placed", "slot": slot, "type": kind, "from_stock": self.stock[kind] > 0,
             "t": round(time.time(), 3), **extra}
        return self._commit(e)

    def retract(self, slot: str, kind: str, **extra) -> dict:
        """Undo a placement the photo check could not confirm, so the planner fills the slot again."""
        if self.placed[(slot, kind)] <= 0:
            raise ValueError(f"nothing recorded in {slot} for {kind}")
        undone = self._open_placement(slot, kind)
        e = {"event": "retracted", "slot": slot, "type": kind, "restored": bool(undone and undone.get("from_stock")),
             "t": round(time.time(), 3), **extra}
        return self._commit(e)

    def remaining(self) -> dict[str, int]:
        out = Counter()
        for s, kinds in self.schedule.items():
            for k in kinds:
                out[k] += max(0, self.need(s, k))
        return dict(out)

    def mismatch(self, seen: dict[str, int]) -> list[str]:
        """Compare pills on the mat with what the week still needs: 'expected 7 white_oval, found 6'."""
        return [f"expected {n} {k}, found {seen.get(k, 0)}" for k, n in sorted(self.remaining().items())
                if seen.get(k, 0) < n]

    def refill_alerts(self, days_left_min: int = 3) -> list[str]:
        per_day = Counter()
        for kinds in self.schedule.values():
            for k, n in kinds.items():
                per_day[k] += n / 7.0
        return [f"refill {k}: {self.stock[k]} left, about {self.stock[k] / r:.0f} days" for k, r in sorted(per_day.items())
                if k in self.stock and r > 0 and self.stock[k] / r < days_left_min]

    def done(self) -> bool:
        return not any(self.remaining().values())

    def summary(self) -> str:
        """Large plain table, one row per day, for a printout or a big-font terminal."""
        rows = [f"{'DAY':<5}{'MORNING':<28}{'EVENING':<28}"]
        for d in DAYS:
            cells = []
            for t in ("AM", "PM"):
                s = f"{d}-{t}"
                want = self.schedule.get(s, {})
                if not want:
                    cells.append("-")
                    continue
                parts = [f"{k} {self.placed[(s, k)]}/{n}" for k, n in want.items()]
                mark = "OK " if all(self.need(s, k) <= 0 for k in want) else ".. "
                cells.append(mark + ", ".join(parts))
            rows.append(f"{d:<5}{cells[0]:<28}{cells[1]:<28}")
        rem = self.remaining()
        rows.append("still needed: " + (", ".join(f"{k} x{n}" for k, n in rem.items() if n) or "nothing, schedule complete"))
        rows += self.refill_alerts()
        return "\n".join(rows)

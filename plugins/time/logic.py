import datetime
import uuid
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from core.logger import logger

# Day name constants for display
DAY_NAMES_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAY_NAMES_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def format_days(days: List[int], lang: str = "cn") -> str:
    """Format a list of day indices (0=Mon..6=Sun) into a human-readable string."""
    if not days:
        return "只响一次"
    if len(days) == 7:
        return "每天"
    weekdays = [0, 1, 2, 3, 4]
    weekends = [5, 6]
    if sorted(days) == weekdays:
        return "工作日"
    if sorted(days) == weekends:
        return "周末"
    names = DAY_NAMES_CN if lang == "cn" else DAY_NAMES_SHORT
    return ", ".join(names[d] for d in sorted(days))


class AlarmManager(QObject):
    """
    Manages alarms, persistence, and triggering.
    Supports both one-time and recurring (days-of-week) alarms.

    Alarm data format:
    {
        "id": str,
        "enabled": bool,
        "hour": int,        # 0-23
        "minute": int,      # 0-59
        "days": list[int],  # 0=Mon..6=Sun, empty = one-time
        "label": str,
    }
    """

    alarms_changed = Signal(list)  # Emitted when alarm list changes

    def __init__(self, context):
        super().__init__()
        self.context = context
        self.state = context.state

        self.alarms: List[Dict] = self.state.get("alarms", [])
        # Migrate old timestamp-based alarms
        self._migrate_alarms()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_alarm_triggered)

        self._current_next: Optional[tuple] = None  # (datetime, alarm_id)

        self._schedule_next_alarm()

    # ── Migration ──────────────────────────────────────────────
    def _migrate_alarms(self):
        """Convert old timestamp-based alarms to new hour/minute format."""
        migrated = False
        for alarm in self.alarms:
            if "timestamp" in alarm and "hour" not in alarm:
                try:
                    dt = datetime.datetime.fromtimestamp(alarm["timestamp"])
                    alarm["hour"] = dt.hour
                    alarm["minute"] = dt.minute
                    alarm["days"] = []  # one-time
                except Exception:
                    alarm["hour"] = 0
                    alarm["minute"] = 0
                    alarm["days"] = []
                alarm.pop("timestamp", None)
                alarm.pop("time_string", None)
                migrated = True
            # Ensure 'days' field exists
            if "days" not in alarm:
                alarm["days"] = []
        if migrated:
            self._save_alarms()

    # ── CRUD ───────────────────────────────────────────────────
    def get_alarms(self) -> List[Dict]:
        return self.alarms

    def add_alarm(self, alarm_data: Dict):
        new_alarm = alarm_data.copy()
        new_alarm["id"] = str(uuid.uuid4())
        new_alarm.setdefault("enabled", True)
        new_alarm.setdefault("days", [])
        new_alarm.setdefault("label", "")
        self.alarms.append(new_alarm)
        self._save_alarms()
        self.alarms_changed.emit(self.alarms)
        self._schedule_next_alarm()

    def update_alarm(self, alarm_id: str, updates: Dict):
        for alarm in self.alarms:
            if alarm["id"] == alarm_id:
                alarm.update(updates)
                self._save_alarms()
                self.alarms_changed.emit(self.alarms)
                self._schedule_next_alarm()
                break

    def remove_alarm(self, alarm_id: str):
        self.alarms = [a for a in self.alarms if a["id"] != alarm_id]
        self._save_alarms()
        self.alarms_changed.emit(self.alarms)
        self._schedule_next_alarm()

    def _save_alarms(self):
        self.state.set("alarms", self.alarms)

    # ── Scheduling ─────────────────────────────────────────────
    def _next_fire_time(
        self, alarm: Dict, now: datetime.datetime
    ) -> Optional[datetime.datetime]:
        """Calculate the next fire time for an alarm from 'now'."""
        hour = alarm.get("hour", 0)
        minute = alarm.get("minute", 0)
        days = alarm.get("days", [])

        if not days:
            # One-time alarm: fire today if still in the future, otherwise tomorrow
            candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate > now:
                return candidate
            return candidate + datetime.timedelta(days=1)

        # Recurring: find the nearest valid day
        best = None
        for offset in range(7):
            candidate_date = now.date() + datetime.timedelta(days=offset)
            weekday = candidate_date.weekday()  # 0=Monday
            if weekday in days:
                candidate = datetime.datetime.combine(
                    candidate_date,
                    datetime.time(hour, minute),
                )
                if candidate > now:
                    if best is None or candidate < best:
                        best = candidate
                    break  # Since we iterate in order, first match is closest
        return best

    def _schedule_next_alarm(self):
        """Finds the nearest upcoming alarm and sets a single-shot timer."""
        self._timer.stop()
        self._current_next = None

        now = datetime.datetime.now()
        nearest_dt = None
        nearest_id = None

        for alarm in self.alarms:
            if not alarm.get("enabled", True):
                continue
            fire_time = self._next_fire_time(alarm, now)
            if fire_time and (nearest_dt is None or fire_time < nearest_dt):
                nearest_dt = fire_time
                nearest_id = alarm["id"]

        if nearest_dt:
            delta = (nearest_dt - now).total_seconds()
            ms = max(0, int(delta * 1000))
            logger.info(
                f"Scheduling next alarm '{nearest_id}' in {delta:.1f}s at {nearest_dt}"
            )
            self._current_next = (nearest_dt, nearest_id)
            self._timer.start(ms)
        else:
            logger.info("No active alarms to schedule.")

    def _on_alarm_triggered(self):
        """Called when the timer fires."""
        if not self._current_next:
            return

        _, alarm_id = self._current_next

        target_alarm = None
        for alarm in self.alarms:
            if alarm["id"] == alarm_id:
                target_alarm = alarm
                break

        if target_alarm:
            logger.info(f"Alarm Triggered: {target_alarm.get('label')}")

            # Send notification
            self.context.send_notification(
                title="闹钟",
                message=target_alarm.get("label") or "闹钟时间到！",
                duration=10000,
            )

            # If one-time (no days), disable it
            if not target_alarm.get("days"):
                target_alarm["enabled"] = False
                self._save_alarms()
                self.alarms_changed.emit(self.alarms)

            # Reschedule for next alarm
            self._schedule_next_alarm()

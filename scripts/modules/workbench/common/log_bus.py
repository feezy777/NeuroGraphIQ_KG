from __future__ import annotations

from collections import deque
from dataclasses import asdict
from threading import Lock
from typing import Any, Deque, Dict, List

from .id_utils import make_id
from .models import TaskLog


class LogBus:
    def __init__(self, max_entries: int = 2000) -> None:
        self._logs: Deque[TaskLog] = deque(maxlen=max_entries)
        self._lock = Lock()
        self._sink = None

    def set_sink(self, sink_callback) -> None:
        self._sink = sink_callback

    def emit(
        self,
        run_id: str,
        module: str,
        message: str,
        level: str = "info",
        event_type: str = "",
        detail_json: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        entry = TaskLog(
            log_id=make_id("log"),
            run_id=run_id or "-",
            level=level,
            event_type=event_type or "log_event",
            message=message,
            module=module,
            detail_json=detail_json or {},
        )
        with self._lock:
            self._logs.append(entry)
        if self._sink:
            try:
                self._sink(asdict(entry))
            except Exception:
                pass
        line = f"[{module}] {message}"
        print(line, flush=True)
        return asdict(entry)

    def recent(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._logs)[-limit:]
        return [asdict(item) for item in items]

    def by_task(self, task_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            items = [it for it in self._logs if it.run_id == task_id]
        return [asdict(item) for item in items]

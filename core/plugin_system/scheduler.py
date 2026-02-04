import time
from typing import Callable, List, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer


class PluginScheduler(QObject):
    """
    Governs resource usage per plugin:
    - QTimer quotas
    - ThreadPool proxying
    - UI rendering/Update throttling
    """

    def __init__(self, plugin_id: str, max_timers: int = 5, max_threads: int = 2):
        super().__init__()
        self.plugin_id = plugin_id
        self.max_timers = max_timers
        self.max_threads = max_threads

        self._active_timers: List[QTimer] = []
        self._thread_pool = QThreadPool()
        self._thread_pool.setMaxThreadCount(max_threads)

        # For UI throttling
        self._last_update_time = 0
        self._update_min_interval = 0.033  # ~30 FPS limit

    def create_timer(self) -> Optional[QTimer]:
        if len(self._active_timers) >= self.max_timers:
            print(f"Plugin {self.plugin_id} exceeded timer quota ({self.max_timers})")
            return None

        timer = QTimer()
        self._active_timers.append(timer)
        # Cleanup when timer is destroyed
        timer.destroyed.connect(
            lambda: self._active_timers.remove(timer)
            if timer in self._active_timers
            else None
        )
        return timer

    def run_async(self, func: Callable, *args, **kwargs):
        """Runs a function in the controlled thread pool."""

        class Worker(QRunnable):
            def run(self):
                func(*args, **kwargs)

        self._thread_pool.start(Worker())

    def request_ui_update(self, widget_update_func: Callable):
        """Throttles UI update requests to maintain frame rate."""
        current_time = time.time()
        if current_time - self._last_update_time >= self._update_min_interval:
            widget_update_func()
            self._last_update_time = current_time
        else:
            # Drop or delay? Simple throttle drops it.
            pass

    def shutdown(self):
        """Reclaims all resources owned by the plugin."""
        for timer in self._active_timers:
            timer.stop()
            timer.deleteLater()
        self._active_timers.clear()
        self._thread_pool.waitForDone()

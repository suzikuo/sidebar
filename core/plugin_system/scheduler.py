import threading
import time
from typing import Callable, List, Optional, Set

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer

from core.logger import logger


class AsyncTaskHandle:
    """Cooperative handle for work submitted to a plugin scheduler."""

    def __init__(self):
        self._lock = threading.RLock()
        self._started = False
        self._done = False
        self._cancel_requested = False
        self._done_event = threading.Event()
        self._done_callbacks = []

    @property
    def running(self) -> bool:
        with self._lock:
            return self._started and not self._done

    @property
    def done(self) -> bool:
        with self._lock:
            return self._done

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancel_requested

    def cancel(self) -> bool:
        """Cancel queued work; running Python code cannot be interrupted safely."""
        with self._lock:
            if self._started or self._done:
                return False
            self._cancel_requested = True
            return True

    def wait(self, timeout: float = None) -> bool:
        return self._done_event.wait(timeout)

    def add_done_callback(self, callback: Callable[["AsyncTaskHandle"], None]):
        with self._lock:
            if not self._done:
                self._done_callbacks.append(callback)
                return
        callback(self)

    def _begin(self) -> bool:
        with self._lock:
            if self._cancel_requested:
                return False
            self._started = True
            return True

    def _finish(self):
        with self._lock:
            if self._done:
                return
            self._done = True
            callbacks = list(self._done_callbacks)
            self._done_callbacks.clear()
            self._done_event.set()

        for callback in callbacks:
            try:
                callback(self)
            except Exception:
                logger.error("Async task completion callback failed.", exc_info=True)


class _Worker(QRunnable):
    def __init__(self, plugin_id, task, func, args, kwargs):
        super().__init__()
        self._plugin_id = plugin_id
        self._task = task
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            if self._task._begin():
                self._func(*self._args, **self._kwargs)
        except Exception:
            logger.error(
                "Unhandled async task error for plugin %s.",
                self._plugin_id,
                exc_info=True,
            )
        finally:
            self._task._finish()


class PluginScheduler(QObject):
    """
    Governs resource usage per plugin:
    - QTimer quotas
    - ThreadPool proxying
    - UI rendering/Update throttling
    """

    DEFAULT_SHUTDOWN_TIMEOUT_MS = 1000

    def __init__(self, plugin_id: str, max_timers: int = 5, max_threads: int = 2):
        super().__init__()
        self.plugin_id = plugin_id
        self.max_timers = max_timers
        self.max_threads = max_threads

        self._active_timers: List[QTimer] = []
        self._active_tasks: Set[AsyncTaskHandle] = set()
        self._thread_pool = QThreadPool()
        self._thread_pool.setMaxThreadCount(max_threads)
        self._lock = threading.RLock()
        self._shutdown = False

        self._last_update_time = 0
        self._update_min_interval = 0.033  # ~30 FPS limit

    @property
    def active_task_count(self) -> int:
        with self._lock:
            return len(self._active_tasks)

    def create_timer(self) -> Optional[QTimer]:
        with self._lock:
            if self._shutdown:
                logger.warning("Plugin %s scheduler is already closed.", self.plugin_id)
                return None
            if len(self._active_timers) >= self.max_timers:
                logger.warning(
                    "Plugin %s exceeded timer quota (%s)",
                    self.plugin_id,
                    self.max_timers,
                )
                return None

            timer = QTimer()
            self._active_timers.append(timer)
            timer.destroyed.connect(lambda *_: self._discard_timer(timer))
            return timer

    def run_async(self, func: Callable, *args, **kwargs) -> AsyncTaskHandle:
        """Run a function in the controlled thread pool and return its handle."""
        if not callable(func):
            raise TypeError("Async task must be callable.")

        task = AsyncTaskHandle()
        task.add_done_callback(self._discard_task)
        worker = _Worker(self.plugin_id, task, func, args, kwargs)

        with self._lock:
            if self._shutdown:
                raise RuntimeError(f"Plugin scheduler is closed: {self.plugin_id}")
            self._active_tasks.add(task)

        try:
            self._thread_pool.start(worker)
        except Exception:
            task._finish()
            raise
        return task

    def request_ui_update(self, widget_update_func: Callable) -> bool:
        """Throttle UI update requests to maintain frame rate."""
        with self._lock:
            if self._shutdown:
                return False
            current_time = time.monotonic()
            if current_time - self._last_update_time < self._update_min_interval:
                return False
            self._last_update_time = current_time

        widget_update_func()
        return True

    def shutdown(self, timeout_ms: int = DEFAULT_SHUTDOWN_TIMEOUT_MS) -> bool:
        """Request cancellation and wait at most ``timeout_ms`` for running work."""
        timeout_ms = max(0, int(timeout_ms))
        with self._lock:
            self._shutdown = True
            timers = list(self._active_timers)
            self._active_timers.clear()
            tasks = list(self._active_tasks)

        for timer in timers:
            try:
                timer.stop()
                timer.deleteLater()
            except RuntimeError:
                pass

        for task in tasks:
            task.cancel()

        completed = self._thread_pool.waitForDone(timeout_ms)
        if not completed:
            logger.warning(
                "Plugin %s still has %s async task(s) after %sms shutdown timeout.",
                self.plugin_id,
                self.active_task_count,
                timeout_ms,
            )
        return completed

    def _discard_timer(self, timer):
        with self._lock:
            self._active_timers = [
                item for item in self._active_timers if item is not timer
            ]

    def _discard_task(self, task):
        with self._lock:
            self._active_tasks.discard(task)

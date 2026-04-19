from __future__ import annotations

import threading
import time
import traceback
from typing import Callable

from .models import CancelledError


class Worker(threading.Thread):
    def __init__(self, app, task_name: str, task_fn: Callable, **kwargs):
        super().__init__(daemon=True)
        self.app = app
        self.task_name = task_name
        self.task_fn = task_fn
        self.kwargs = kwargs

    def run(self):
        start = time.time()
        try:
            result = self.task_fn(**self.kwargs)
            self.app.queue.put({"type": "done", "task": self.task_name, "result": result, "elapsed": time.time() - start})
        except CancelledError as exc:
            self.app.queue.put({"type": "cancelled", "task": self.task_name, "message": str(exc), "elapsed": time.time() - start})
        except Exception as exc:
            self.app.queue.put(
                {
                    "type": "error",
                    "task": self.task_name,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                    "elapsed": time.time() - start,
                }
            )

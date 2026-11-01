"""Tasks must land on a queue that the production worker consumes."""

import re
from pathlib import Path

from config.celery import app


def _worker_queues() -> set[str]:
    entrypoint = Path(__file__).resolve().parents[2] / "entrypoint.sh"
    return set(re.search(r"-Q (\S+)", entrypoint.read_text()).group(1).split(","))


def test_worker_consumes_the_default_queue():
    assert app.conf.task_default_queue in _worker_queues()


def test_worker_consumes_every_queue_named_by_a_task():
    app.loader.import_default_modules()
    named = {task.queue for task in app.tasks.values() if getattr(task, "queue", None)}

    assert named <= _worker_queues()

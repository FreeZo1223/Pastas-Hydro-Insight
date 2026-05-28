"""Background-task registry + helpers voor zichtbare progress in de UI.

Gebruik:

    from pastasdash_v2.tasks import run_task

    async def fit_button_handler():
        async with run_task("Model fitten: GMW123_1"):
            ml = await asyncio.to_thread(slow_fit, ...)

Het label verschijnt in de header-spinner, en bij voltooiing krijgt de
gebruiker een notification. Excepties worden opgevangen en als
foutnotificatie getoond — de app crasht niet.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterator, TypeVar

from nicegui import ui

log = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class Task:
    id: str
    label: str
    started_at: float
    error: str | None = None


@dataclass
class TaskRegistry:
    active: dict[str, Task] = field(default_factory=dict)
    listeners: list[Callable[[], None]] = field(default_factory=list)

    def add(self, label: str) -> Task:
        t = Task(id=str(uuid.uuid4()), label=label, started_at=asyncio.get_event_loop().time())
        self.active[t.id] = t
        self._notify()
        return t

    def finish(self, task_id: str, error: str | None = None) -> None:
        t = self.active.pop(task_id, None)
        if t is not None:
            t.error = error
        self._notify()

    def on_change(self, cb: Callable[[], None]) -> None:
        self.listeners.append(cb)

    def _notify(self) -> None:
        for cb in self.listeners:
            try:
                cb()
            except Exception as exc:  # noqa: BLE001
                log.warning("Task listener faalde: %s", exc)

    def labels(self) -> list[str]:
        return [t.label for t in self.active.values()]

    def __len__(self) -> int:
        return len(self.active)


REGISTRY = TaskRegistry()


@asynccontextmanager
async def run_task(label: str, notify_on_success: bool = False) -> Iterator[None]:
    """Async context manager: registreer + toon spinner tijdens een lang lopende taak."""
    task = REGISTRY.add(label)
    log.info("Task gestart: %s", label)
    try:
        yield
    except Exception as exc:  # noqa: BLE001
        log.exception("Task gefaald: %s", label)
        REGISTRY.finish(task.id, error=str(exc))
        try:
            ui.notify(f"Fout in '{label}': {exc}", type="negative", timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        raise
    else:
        REGISTRY.finish(task.id)
        if notify_on_success:
            try:
                ui.notify(f"Klaar: {label}", type="positive", timeout=3000)
            except Exception:  # noqa: BLE001
                pass


async def run_in_thread(label: str, fn: Callable[..., T], *args: Any, notify: bool = False, **kwargs: Any) -> T:
    """Run een blocking callable in een threadpool, getrackt door de registry."""
    async with run_task(label, notify_on_success=notify):
        return await asyncio.to_thread(fn, *args, **kwargs)


async def gather_with_progress(
    label: str,
    coros: list[Awaitable[T]],
    notify: bool = False,
) -> list[T]:
    """Voer meerdere coroutines parallel uit binnen één progress-label."""
    async with run_task(label, notify_on_success=notify):
        return await asyncio.gather(*coros)

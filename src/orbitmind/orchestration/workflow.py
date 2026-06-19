"""In-process deterministic workflow engine (ADR-0004).

Defines a minimal ``WorkflowEngine`` interface so a Temporal-backed implementation
can be substituted later without changing callers. The in-process implementation
records ordered, timed steps onto a :class:`WorkflowRun`.
"""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from contextlib import AbstractContextManager, contextmanager
from typing import Any, Protocol

from orbitmind.core.timeutils import utcnow
from orbitmind.orchestration.models import WorkflowRun, WorkflowStatus, WorkflowStep


class WorkflowContext(Protocol):
    """A running workflow that records steps and yields a final ``WorkflowRun``."""

    def step(self, name: str) -> AbstractContextManager[MutableMapping[str, Any]]:
        """Return a context manager recording one timed step (yields a detail dict)."""
        ...

    def complete(self) -> WorkflowRun: ...
    def fail(self) -> WorkflowRun: ...


class WorkflowEngine(Protocol):
    """Factory for workflow executions (swap-in point for Temporal later)."""

    def start(self, *, mission_id: str, name: str) -> InProcessWorkflowContext: ...


class InProcessWorkflowContext:
    """Records timed steps synchronously in-process."""

    def __init__(self, run: WorkflowRun) -> None:
        self._run = run

    @contextmanager
    def step(self, name: str) -> Iterator[MutableMapping[str, Any]]:
        started = utcnow()
        detail: dict[str, Any] = {}
        try:
            yield detail
        except Exception as exc:  # record the failure on the step, then re-raise
            self._run.steps.append(
                WorkflowStep(
                    name=name,
                    status="error",
                    started_at=started,
                    finished_at=utcnow(),
                    detail={**detail, "error": str(exc)},
                )
            )
            raise
        else:
            self._run.steps.append(
                WorkflowStep(
                    name=name,
                    status="ok",
                    started_at=started,
                    finished_at=utcnow(),
                    detail=detail,
                )
            )

    def complete(self) -> WorkflowRun:
        self._run.status = WorkflowStatus.COMPLETED
        self._run.finished_at = utcnow()
        return self._run

    def fail(self) -> WorkflowRun:
        self._run.status = WorkflowStatus.FAILED
        self._run.finished_at = utcnow()
        return self._run


class InProcessWorkflowEngine:
    """Default Phase 1 engine: deterministic, synchronous, in-process."""

    def start(self, *, mission_id: str, name: str) -> InProcessWorkflowContext:
        run = WorkflowRun(mission_id=mission_id, workflow_name=name)
        return InProcessWorkflowContext(run)

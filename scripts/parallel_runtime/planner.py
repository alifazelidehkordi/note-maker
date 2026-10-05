from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, TypeVar

from .models import (
    JobPlan,
    ManifestTransition,
    PlannedJob,
    PlanningCandidate,
    PlanningOptions,
    TransitionKind,
)

T = TypeVar("T")


class ManifestReader(Protocol):
    def get(self, key: str) -> dict | None: ...

    def inspect(
        self,
        job,
        *,
        overwrite: bool = False,
        resume: bool = True,
        adopt_existing: bool = False,
        retry_failed_only: bool = False,
    ): ...


def plan_jobs(
    candidates: Iterable[PlanningCandidate[T]],
    manifest: ManifestReader,
    *,
    run_id: str,
    options: PlanningOptions | None = None,
) -> JobPlan[T]:
    """Build a complete browser-free execution plan.

    This function never mutates the manifest and never creates a browser. It
    returns explicit transitions for the coordinator-owned writer to commit in
    one batch before worker startup.
    """
    from manifest import DecisionAction

    opts = options or PlanningOptions()
    candidate_list = tuple(candidates)
    runnable: list[PlannedJob[T]] = []
    skipped: dict[str, str] = {}
    adopted: list[str] = []
    transitions: list[ManifestTransition] = []
    completed_skip_count = 0

    for candidate in candidate_list:
        job = candidate.job
        existing = manifest.get(job.key)
        decision = manifest.inspect(
            job,
            overwrite=opts.overwrite,
            resume=opts.resume,
            adopt_existing=opts.adopt_existing,
            retry_failed_only=opts.retry_failed_only,
        )

        if decision.action == DecisionAction.ADOPT:
            adopted.append(candidate.label)
            transitions.append(
                ManifestTransition(TransitionKind.ADOPTED, job, decision.reason)
            )
            continue

        if decision.action == DecisionAction.SKIP:
            skipped[candidate.label] = decision.reason
            if decision.reason == "completed output is valid":
                completed_skip_count += 1
            continue

        if existing and existing.get("status") == "running":
            transitions.append(
                ManifestTransition(
                    TransitionKind.INTERRUPTED,
                    job,
                    "previous coordinator stopped while the job was running",
                )
            )
        if decision.invalidate:
            transitions.append(
                ManifestTransition(TransitionKind.INVALIDATED, job, decision.reason)
            )
        elif existing is None:
            transitions.append(
                ManifestTransition(TransitionKind.PENDING, job, decision.reason)
            )

        runnable.append(
            PlannedJob(
                candidate=candidate,
                reason=decision.reason,
                previous_status=decision.previous_status,
            )
        )

    return JobPlan(
        run_id=run_id,
        candidates=candidate_list,
        runnable=tuple(runnable),
        skipped=skipped,
        adopted=tuple(adopted),
        completed_skip_count=completed_skip_count,
        transitions=tuple(transitions),
    )

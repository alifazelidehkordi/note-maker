"""Parallel planning primitives and Level-5 process runtime.

Runtime modules are intentionally not imported here because ``manifest`` imports
``parallel_runtime.models`` while the coordinator itself imports ``manifest``.
Callers should import coordinator/claims/event_bus explicitly.
"""

from .models import (
    ExecutionJob,
    JobPlan,
    ManifestTransition,
    PlannedJob,
    PlanningCandidate,
    PlanningOptions,
    RunConfig,
    TransitionKind,
    WorkerExecutionResult,
    estimate_file_weight,
    estimate_text_weight,
)
from .planner import plan_jobs
from .resilience import (
    FailureCategory,
    GlobalRuntimeController,
    RetryBudgetPolicy,
    RetryDecision,
    RetryTracker,
    classify_failure,
)

__all__ = [
    "ExecutionJob",
    "JobPlan",
    "ManifestTransition",
    "PlannedJob",
    "PlanningCandidate",
    "PlanningOptions",
    "RunConfig",
    "TransitionKind",
    "WorkerExecutionResult",
    "estimate_file_weight",
    "estimate_text_weight",
    "plan_jobs",
    "FailureCategory",
    "GlobalRuntimeController",
    "RetryBudgetPolicy",
    "RetryDecision",
    "RetryTracker",
    "classify_failure",
]

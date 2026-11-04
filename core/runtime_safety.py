"""Fault-isolated async provider execution for Nova Umbrella.

The runner returns one outcome per task. A provider failure never cancels sibling tasks.
It intentionally does not catch BaseException, so cancellation and process interrupts propagate.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Iterable


class OutcomeStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED_CIRCUIT_OPEN = "skipped_circuit_open"


@dataclass(frozen=True)
class TaskOutcome:
    task_id: str
    provider: str
    status: OutcomeStatus
    value: Any = None
    error: str | None = None
    attempts: int = 0
    latency_ms: float = 0.0


class CircuitBreaker:
    """Small process-local breaker; use a shared store for multi-worker deployments."""

    def __init__(self, failure_threshold: int = 3, reset_timeout: float = 30.0) -> None:
        if failure_threshold < 1 or reset_timeout <= 0:
            raise ValueError("failure_threshold and reset_timeout must be positive")
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.failures = 0
        self.opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self.opened_at is None:
            return False
        if time.monotonic() - self.opened_at >= self.reset_timeout:
            self.opened_at = None
            self.failures = 0
            return False
        return True

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.opened_at = time.monotonic()


async def execute_isolated(
    task_id: str,
    provider: str,
    operation: Callable[[], Awaitable[Any]],
    *,
    breaker: CircuitBreaker | None = None,
    timeout_seconds: float = 20.0,
    retries: int = 0,
) -> TaskOutcome:
    if timeout_seconds <= 0 or retries < 0:
        raise ValueError("timeout_seconds must be positive and retries non-negative")
    if breaker is not None and breaker.is_open:
        return TaskOutcome(task_id, provider, OutcomeStatus.SKIPPED_CIRCUIT_OPEN,
                           error="provider circuit is open")
    started = time.perf_counter()
    attempts = 0
    while attempts <= retries:
        attempts += 1
        try:
            value = await asyncio.wait_for(operation(), timeout=timeout_seconds)
            if breaker:
                breaker.record_success()
            return TaskOutcome(task_id, provider, OutcomeStatus.SUCCEEDED, value=value,
                               attempts=attempts, latency_ms=(time.perf_counter()-started)*1000)
        except (Exception, asyncio.TimeoutError) as exc:
            if breaker:
                breaker.record_failure()
            if attempts > retries:
                return TaskOutcome(task_id, provider, OutcomeStatus.FAILED,
                                   error=f"{type(exc).__name__}: {exc}", attempts=attempts,
                                   latency_ms=(time.perf_counter()-started)*1000)
    raise AssertionError("unreachable")


async def execute_many_isolated(
    tasks: Iterable[tuple[str, str, Callable[[], Awaitable[Any]], CircuitBreaker | None]],
    *,
    timeout_seconds: float = 20.0,
    retries: int = 0,
) -> list[TaskOutcome]:
    """Execute independent tasks concurrently and preserve every task outcome."""
    async def run(item: tuple[str, str, Callable[[], Awaitable[Any]], CircuitBreaker | None]) -> TaskOutcome:
        task_id, provider, operation, breaker = item
        return await execute_isolated(task_id, provider, operation, breaker=breaker,
                                       timeout_seconds=timeout_seconds, retries=retries)
    return list(await asyncio.gather(*(run(item) for item in tasks)))


class ActionDecision(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    DENY = "DENY"


@dataclass(frozen=True)
class GovernanceResult:
    decision: ActionDecision
    reason: str


def authorize_commercial_action(
    *, authenticated: bool, tenant_match: bool, approval_required: bool,
    approval_granted: bool, action_allowed: bool,
) -> GovernanceResult:
    """Fail closed: identity/tenant mismatch or prohibited actions are denied."""
    if not authenticated:
        return GovernanceResult(ActionDecision.DENY, "authentication required")
    if not tenant_match:
        return GovernanceResult(ActionDecision.DENY, "tenant boundary mismatch")
    if not action_allowed:
        return GovernanceResult(ActionDecision.DENY, "action prohibited by policy")
    if approval_required and not approval_granted:
        return GovernanceResult(ActionDecision.REQUIRE_APPROVAL, "explicit approval required")
    return GovernanceResult(ActionDecision.ALLOW, "policy checks passed")

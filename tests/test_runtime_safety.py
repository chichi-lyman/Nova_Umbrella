import asyncio
import pytest

from core.runtime_safety import (
    ActionDecision, CircuitBreaker, OutcomeStatus, authorize_commercial_action,
    execute_isolated, execute_many_isolated,
)


@pytest.mark.asyncio
async def test_failed_provider_does_not_cancel_sibling_tasks():
    async def good():
        await asyncio.sleep(0)
        return "ok"
    async def bad():
        raise ConnectionError("provider offline")
    outcomes = await execute_many_isolated([
        ("a", "healthy", good, None),
        ("b", "missing", bad, None),
    ], retries=0)
    assert [item.status for item in outcomes] == [OutcomeStatus.SUCCEEDED, OutcomeStatus.FAILED]
    assert outcomes[0].value == "ok"
    assert "provider offline" in outcomes[1].error


@pytest.mark.asyncio
async def test_retry_and_breaker_open():
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout=10)
    async def fail():
        raise TimeoutError("slow")
    first = await execute_isolated("x", "p", fail, breaker=breaker, retries=1)
    second = await execute_isolated("y", "p", fail, breaker=breaker)
    third = await execute_isolated("z", "p", fail, breaker=breaker)
    assert first.attempts == 2
    assert second.status == OutcomeStatus.FAILED
    assert third.status == OutcomeStatus.SKIPPED_CIRCUIT_OPEN


def test_governance_is_fail_closed_and_requires_explicit_approval():
    assert authorize_commercial_action(authenticated=False, tenant_match=True,
        approval_required=False, approval_granted=False, action_allowed=True).decision == ActionDecision.DENY
    assert authorize_commercial_action(authenticated=True, tenant_match=True,
        approval_required=True, approval_granted=False, action_allowed=True).decision == ActionDecision.REQUIRE_APPROVAL
    assert authorize_commercial_action(authenticated=True, tenant_match=True,
        approval_required=True, approval_granted=True, action_allowed=True).decision == ActionDecision.ALLOW

from __future__ import annotations

import json

import pytest

from core.sovereign_oracle.audit import GENESIS, HashChainLedger, canonical_json, deterministic_memory_id


def test_canonical_json_and_content_id_are_stable() -> None:
    assert canonical_json({"b": 2, "a": 1}) == canonical_json({"a": 1, "b": 2})
    item = {"state": "ready", "sequence": 3}
    assert deterministic_memory_id("workspace-1", item) == deterministic_memory_id("workspace-1", item)
    assert deterministic_memory_id("workspace-1", item) != deterministic_memory_id("workspace-2", item)


def test_hash_chain_links_and_verifies_records() -> None:
    ledger = HashChainLedger()
    one = ledger.append("orchestrator", "job.accepted", {"job": "abc"})
    two = ledger.append("agent", "job.finished", {"job": "abc"})
    assert one.sequence == 0 and one.previous_hash == GENESIS
    assert two.sequence == 1 and two.previous_hash == one.record_hash
    assert ledger.verify()
    assert ledger.export_json()["verified"] is True


def test_disk_roundtrip_and_tamper_detection(tmp_path) -> None:
    file_path = tmp_path / "events.jsonl"
    ledger = HashChainLedger(file_path)
    ledger.append("orchestrator", "job.accepted", {"job": "abc"})
    assert HashChainLedger(file_path).verify()

    record = json.loads(file_path.read_text(encoding="utf-8"))
    record["payload"]["job"] = "changed"
    file_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="integrity verification failed"):
        HashChainLedger(file_path)


@pytest.mark.parametrize(("actor", "kind"), [("", "event"), ("agent", ""), (" ", "event")])
def test_append_requires_actor_and_event_type(actor: str, kind: str) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        HashChainLedger().append(actor, kind, {})

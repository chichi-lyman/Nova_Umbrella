from core.webhook_security import WebhookVerifier


def test_hmac_verification_rejects_replay_and_tampering():
    verifier = WebhookVerifier("x" * 40)
    body, timestamp = b'{"id":"evt-1"}', 1700000000
    signature = verifier.sign(timestamp, body)
    assert verifier.verify(timestamp=timestamp, body=body, signature=signature,
                           event_id="evt-1", now=timestamp)
    assert not verifier.verify(timestamp=timestamp, body=body, signature=signature,
                                event_id="evt-1", now=timestamp)
    assert not verifier.verify(timestamp=timestamp, body=body+b" ", signature=signature,
                                event_id="evt-2", now=timestamp)


def test_hmac_verification_rejects_stale_events():
    verifier = WebhookVerifier("x" * 40, tolerance_seconds=30)
    timestamp = 1000
    assert not verifier.verify(timestamp=timestamp, body=b"{}", signature=verifier.sign(timestamp,b"{}"),
                               event_id="old", now=1100)

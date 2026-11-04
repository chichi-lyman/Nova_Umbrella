"""Minimal HMAC webhook verification and bounded replay protection."""
from __future__ import annotations

import hashlib
import hmac
import time
from collections import OrderedDict


class WebhookVerifier:
    def __init__(self, secret: str, *, tolerance_seconds: int = 300, max_seen: int = 10000) -> None:
        if len(secret) < 32:
            raise ValueError("webhook secret must contain at least 32 characters")
        if tolerance_seconds < 1 or max_seen < 1:
            raise ValueError("tolerance_seconds and max_seen must be positive")
        self._secret = secret.encode()
        self.tolerance_seconds = tolerance_seconds
        self.max_seen = max_seen
        self._seen: OrderedDict[str, float] = OrderedDict()

    def sign(self, timestamp: int, body: bytes) -> str:
        message = str(timestamp).encode() + b"." + body
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()

    def verify(self, *, timestamp: int, body: bytes, signature: str,
               event_id: str, now: float | None = None) -> bool:
        current = time.time() if now is None else now
        if not event_id or abs(current - timestamp) > self.tolerance_seconds:
            return False
        expected = self.sign(timestamp, body)
        if not hmac.compare_digest(expected, signature):
            return False
        # Record only after cryptographic and freshness checks.
        if event_id in self._seen:
            return False
        self._seen[event_id] = current
        while len(self._seen) > self.max_seen:
            self._seen.popitem(last=False)
        return True

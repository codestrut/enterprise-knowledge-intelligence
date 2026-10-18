"""Bounded, expiring in-process throttling for sign-in and token refresh failures.

Deployment constraint: the API runs as a single Uvicorn worker. Counters live only in this
process, reset when it restarts, and are not shared between workers or replicas; a
multi-worker deployment needs a shared store before relying on this protection.

Policy (defaults):
* Per account/address pair: the first ``free_failures`` (5) failures are free; from then on
  each failure blocks the pair for ``base_delay * 2**(failures - free_failures)`` seconds,
  capped at ``max_delay`` (15 minutes). An account is never locked globally: other client
  addresses are unaffected by a pair's backoff.
* Per address: at most ``ip_max_failures`` (50) failures per ``ip_window`` (15 minutes)
  across all accounts, as a looser cap against credential spraying.
* Entries expire after ``idle_ttl`` (15 minutes) without failures once no block is active, and
  total storage is bounded by ``max_entries`` (oldest entries are evicted first).
* Callers record only failed verifications, so a throttled response looks the same whether
  or not the account exists.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import math
from threading import Lock
import time
from typing import Callable


@dataclass
class _PairState:
    failures: int
    blocked_until: float
    last_failure: float


@dataclass
class _AddressState:
    failures: int
    window_start: float


class FailureThrottle:
    """Track failed attempts per account/address pair and per address."""

    def __init__(
        self,
        *,
        free_failures: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 900.0,
        ip_max_failures: int = 50,
        ip_window: float = 900.0,
        idle_ttl: float = 900.0,
        max_entries: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if min(free_failures, ip_max_failures, max_entries) < 1:
            raise ValueError("Throttle counts must be positive.")
        if min(base_delay, max_delay, ip_window, idle_ttl) <= 0:
            raise ValueError("Throttle durations must be positive.")
        self._free_failures = free_failures
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._ip_max_failures = ip_max_failures
        self._ip_window = ip_window
        self._idle_ttl = idle_ttl
        self._max_entries = max_entries
        self._clock = clock
        self._pairs: OrderedDict[tuple[str, str], _PairState] = OrderedDict()
        self._addresses: OrderedDict[str, _AddressState] = OrderedDict()
        self._lock = Lock()

    @staticmethod
    def _pair_key(address: str, account: object) -> tuple[str, str]:
        normalised = account.strip().casefold() if isinstance(account, str) else ""
        return normalised, address

    def retry_after(self, address: str, account: object = None) -> int | None:
        """Seconds the caller must wait, or None when the attempt may proceed."""
        now = self._clock()
        with self._lock:
            self._prune(now)
            waits = []
            pair = self._pairs.get(self._pair_key(address, account))
            if pair is not None and pair.blocked_until > now:
                waits.append(pair.blocked_until - now)
            state = self._addresses.get(address)
            if state is not None and state.failures >= self._ip_max_failures:
                waits.append(state.window_start + self._ip_window - now)
        if not waits:
            return None
        return max(1, math.ceil(max(waits)))

    def record_failure(self, address: str, account: object = None) -> None:
        now = self._clock()
        key = self._pair_key(address, account)
        with self._lock:
            self._prune(now)
            pair = self._pairs.pop(key, None) or _PairState(0, 0.0, now)
            pair.failures += 1
            pair.last_failure = now
            if pair.failures >= self._free_failures:
                exponent = min(pair.failures - self._free_failures, 32)
                pair.blocked_until = now + min(self._base_delay * 2**exponent, self._max_delay)
            self._pairs[key] = pair
            state = self._addresses.pop(address, None)
            if state is None or now - state.window_start >= self._ip_window:
                state = _AddressState(0, now)
            state.failures += 1
            self._addresses[address] = state
            self._enforce_bound()

    def record_success(self, address: str, account: object = None) -> None:
        """Clear the pair's backoff; the looser per-address window is left to expire."""
        with self._lock:
            self._pairs.pop(self._pair_key(address, account), None)

    def entry_count(self) -> int:
        with self._lock:
            self._prune(self._clock())
            return len(self._pairs) + len(self._addresses)

    def _prune(self, now: float) -> None:
        expired_pairs = [
            key
            for key, pair in self._pairs.items()
            if pair.blocked_until <= now and now - pair.last_failure >= self._idle_ttl
        ]
        for key in expired_pairs:
            del self._pairs[key]
        expired_addresses = [
            address
            for address, state in self._addresses.items()
            if now - state.window_start >= self._ip_window
        ]
        for address in expired_addresses:
            del self._addresses[address]

    def _enforce_bound(self) -> None:
        while len(self._pairs) + len(self._addresses) > self._max_entries:
            larger = self._pairs if len(self._pairs) >= len(self._addresses) else self._addresses
            larger.popitem(last=False)

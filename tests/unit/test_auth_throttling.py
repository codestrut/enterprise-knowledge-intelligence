"""In-process sign-in throttling and Argon2 concurrency cap (single-worker deployment)."""

import threading
import time

import pytest

from src.auth import passwords
from src.auth.throttling import FailureThrottle


class FakeClock:
    def __init__(self, start=1_000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_backoff_starts_after_free_failures_grows_and_is_capped():
    clock = FakeClock()
    throttle = FailureThrottle(free_failures=5, base_delay=1.0, max_delay=900.0, clock=clock)
    for _ in range(4):
        throttle.record_failure("198.51.100.1", "user@example.test")
    assert throttle.retry_after("198.51.100.1", "user@example.test") is None
    delays = []
    for _ in range(16):
        throttle.record_failure("198.51.100.1", "user@example.test")
        delays.append(throttle.retry_after("198.51.100.1", "user@example.test"))
    assert delays[:4] == [1, 2, 4, 8]
    assert delays == sorted(delays)
    assert max(delays) == 900


def test_pair_backoff_does_not_lock_the_account_from_other_addresses():
    throttle = FailureThrottle(free_failures=3, clock=FakeClock())
    for _ in range(3):
        throttle.record_failure("198.51.100.1", "user@example.test")
    assert throttle.retry_after("198.51.100.1", "user@example.test") is not None
    assert throttle.retry_after("203.0.113.9", "user@example.test") is None
    assert throttle.retry_after("198.51.100.1", "other@example.test") is None


def test_per_address_cap_is_looser_and_expires_with_its_window():
    clock = FakeClock()
    throttle = FailureThrottle(free_failures=5, ip_max_failures=20, ip_window=900.0, clock=clock)
    for index in range(20):
        throttle.record_failure("198.51.100.1", f"user-{index}@example.test")
    assert throttle.retry_after("198.51.100.1", "fresh@example.test") is not None
    assert throttle.retry_after("203.0.113.9", "fresh@example.test") is None
    clock.advance(901)
    assert throttle.retry_after("198.51.100.1", "fresh@example.test") is None


def test_success_clears_the_pair_counter_only():
    throttle = FailureThrottle(free_failures=2, ip_max_failures=3, clock=FakeClock())
    throttle.record_failure("198.51.100.1", "user@example.test")
    throttle.record_success("198.51.100.1", "user@example.test")
    throttle.record_failure("198.51.100.1", "user@example.test")
    assert throttle.retry_after("198.51.100.1", "user@example.test") is None
    throttle.record_failure("198.51.100.1", "another@example.test")
    assert throttle.retry_after("198.51.100.1", "third@example.test") is not None


def test_counters_expire_after_idle_period():
    clock = FakeClock()
    throttle = FailureThrottle(free_failures=2, idle_ttl=900.0, clock=clock)
    throttle.record_failure("198.51.100.1", "user@example.test")
    throttle.record_failure("198.51.100.1", "user@example.test")
    assert throttle.retry_after("198.51.100.1", "user@example.test") is not None
    clock.advance(901)
    assert throttle.retry_after("198.51.100.1", "user@example.test") is None
    assert throttle.entry_count() == 0


def test_counter_storage_is_bounded():
    throttle = FailureThrottle(max_entries=10, clock=FakeClock())
    for index in range(25):
        throttle.record_failure(f"198.51.100.{index}", f"user-{index}@example.test")
    assert throttle.entry_count() <= 10


def test_account_keys_are_normalised():
    throttle = FailureThrottle(free_failures=2, clock=FakeClock())
    throttle.record_failure("198.51.100.1", " User@Example.TEST ")
    throttle.record_failure("198.51.100.1", "user@example.test")
    assert throttle.retry_after("198.51.100.1", "USER@example.test") is not None


def test_argon2_verification_concurrency_never_exceeds_the_cap(monkeypatch):
    lock = threading.Lock()
    state = {"active": 0, "peak": 0}

    class SlowHasher:
        def verify(self, encoded_hash, password):
            with lock:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            time.sleep(0.05)
            with lock:
                state["active"] -= 1
            return True

    monkeypatch.setattr(passwords, "_PASSWORD_HASHER", SlowHasher())
    monkeypatch.setattr(passwords, "_VERIFY_SLOTS", threading.BoundedSemaphore(2))
    threads = [
        threading.Thread(target=passwords.verify_password, args=("violet-cactus-orbit-sailed", "$argon2id$stub"))
        for _ in range(10)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert state["peak"] == 2


@pytest.mark.parametrize("value, expected", [(None, 4), ("1", 1), ("3", 3), ("16", 16)])
def test_argon2_concurrency_setting_accepts_bounded_values(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("EKIP_ARGON2_MAX_CONCURRENCY", raising=False)
    else:
        monkeypatch.setenv("EKIP_ARGON2_MAX_CONCURRENCY", value)
    assert passwords.argon2_concurrency_from_environment() == expected


@pytest.mark.parametrize("value", ["0", "-1", "17", "many", ""])
def test_argon2_concurrency_setting_rejects_unsafe_values(monkeypatch, value):
    monkeypatch.setenv("EKIP_ARGON2_MAX_CONCURRENCY", value)
    with pytest.raises(ValueError, match="EKIP_ARGON2_MAX_CONCURRENCY"):
        passwords.argon2_concurrency_from_environment()

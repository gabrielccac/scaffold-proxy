from __future__ import annotations

from scaffold_proxy.config import Settings
from scaffold_proxy.scoring import compute_score, decide_status, reset_to_fresh_fields


def _settings(**kwargs) -> Settings:
    base = Settings()
    from dataclasses import replace

    return replace(base, **kwargs)


def test_alive_on_fast_success() -> None:
    s = _settings(fast_latency_ms=5000, dead_after_failures=3, retire_after_failures=10)
    b = compute_score(
        recent_oks=[True],
        recent_latencies=[800.0],
        consecutive_successes=1,
        consecutive_failures=0,
        last_ok=True,
        last_latency_ms=800.0,
        settings=s,
    )
    assert b.status == "alive"
    assert b.score > 50


def test_degraded_on_slow_success() -> None:
    s = _settings(fast_latency_ms=5000)
    b = compute_score(
        recent_oks=[True],
        recent_latencies=[7000.0],
        consecutive_successes=1,
        consecutive_failures=0,
        last_ok=True,
        last_latency_ms=7000.0,
        settings=s,
    )
    assert b.status == "degraded"


def test_dead_then_retired() -> None:
    s = _settings(dead_after_failures=3, retire_after_failures=10)
    assert (
        decide_status(
            last_ok=False,
            last_latency_ms=1000,
            consecutive_successes=0,
            consecutive_failures=3,
            window_uptime=0.0,
            settings=s,
        )
        == "dead"
    )
    assert (
        decide_status(
            last_ok=False,
            last_latency_ms=1000,
            consecutive_successes=0,
            consecutive_failures=10,
            window_uptime=0.0,
            settings=s,
        )
        == "retired"
    )


def test_reset_to_fresh_fields() -> None:
    fields = reset_to_fresh_fields()
    assert fields["status"] == "pending"
    assert fields["consecutive_failures"] == 0
    assert fields["retired_at"] is None

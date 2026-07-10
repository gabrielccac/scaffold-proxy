from __future__ import annotations

from dataclasses import dataclass

from scaffold_proxy.config import Settings


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    score: float
    window_uptime: float
    latency_score: float
    freshness: float
    streak_bonus: float
    avg_latency_ms: float | None
    status: str


def _latency_score(latency_ms: float | None, timeout_ms: float) -> float:
    if latency_ms is None:
        return 0.0
    if latency_ms <= 1000:
        return 1.0
    if latency_ms >= timeout_ms:
        return 0.0
    return max(0.0, 1.0 - (latency_ms - 1000) / (timeout_ms - 1000))


def _freshness(checks_in_window: int, window: int) -> float:
    # More recent successful activity approximated by filled window density.
    if window <= 0:
        return 0.0
    return min(1.0, checks_in_window / max(1, min(window, 5)))


def compute_score(
    *,
    recent_oks: list[bool],
    recent_latencies: list[float | None],
    consecutive_successes: int,
    consecutive_failures: int,
    last_ok: bool | None,
    last_latency_ms: float | None,
    settings: Settings,
) -> ScoreBreakdown:
    window = max(1, settings.score_window)
    oks = recent_oks[-window:]
    lats = recent_latencies[-window:]
    if not oks:
        status = "pending"
        return ScoreBreakdown(0.0, 0.0, 0.0, 0.0, 0.0, None, status)

    window_uptime = sum(1 for x in oks if x) / len(oks)
    ok_lats = [x for x, ok in zip(lats, oks) if ok and x is not None]
    avg_latency = (sum(ok_lats) / len(ok_lats)) if ok_lats else None
    timeout_ms = settings.validate_timeout_seconds * 1000
    # Only successful checks contribute to latency score.
    latency_score = _latency_score(avg_latency, timeout_ms) if avg_latency is not None else 0.0
    freshness = _freshness(len(oks), window)
    streak_bonus = min(1.0, consecutive_successes / 5.0)

    score = 100.0 * (
        0.50 * window_uptime
        + 0.25 * latency_score
        + 0.15 * freshness
        + 0.10 * streak_bonus
    )

    status = decide_status(
        last_ok=last_ok,
        last_latency_ms=last_latency_ms,
        consecutive_successes=consecutive_successes,
        consecutive_failures=consecutive_failures,
        window_uptime=window_uptime,
        settings=settings,
    )
    return ScoreBreakdown(
        score=round(score, 2),
        window_uptime=round(window_uptime, 4),
        latency_score=round(latency_score, 4),
        freshness=round(freshness, 4),
        streak_bonus=round(streak_bonus, 4),
        avg_latency_ms=(round(avg_latency, 1) if avg_latency is not None else None),
        status=status,
    )


def decide_status(
    *,
    last_ok: bool | None,
    last_latency_ms: float | None,
    consecutive_successes: int,
    consecutive_failures: int,
    window_uptime: float,
    settings: Settings,
) -> str:
    if last_ok is None and consecutive_successes == 0 and consecutive_failures == 0:
        return "pending"

    if consecutive_failures >= settings.retire_after_failures:
        return "retired"
    if consecutive_failures >= settings.dead_after_failures:
        return "dead"

    if last_ok:
        if (last_latency_ms or 0) > settings.fast_latency_ms or window_uptime < 0.5:
            return "degraded"
        return "alive"

    # Last failed but not enough consecutive failures yet → degraded if any history of success
    if consecutive_successes > 0 or window_uptime > 0:
        return "degraded"
    return "dead"


def reset_to_fresh_fields() -> dict:
    """Fields to apply when a retired/dead proxy is seen again in scrape."""
    return {
        "status": "pending",
        "consecutive_successes": 0,
        "consecutive_failures": 0,
        "score": None,
        "retired_at": None,
        "last_error": None,
    }

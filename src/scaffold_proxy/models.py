from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


STATUSES = ("pending", "alive", "degraded", "dead", "retired")


@dataclass(slots=True)
class ProxyRecord:
    host: str
    port: int
    protocol: str
    source: str = "freeproxy.world"
    country: str | None = None
    city: str | None = None
    anonymity: str | None = None
    listed_speed_ms: int | None = None
    first_seen_at: str = field(default_factory=utc_now)
    last_seen_at: str = field(default_factory=utc_now)
    status: str = "pending"  # pending|alive|degraded|dead|retired
    last_checked_at: str | None = None
    last_latency_ms: float | None = None
    egress_ip: str | None = None
    egress_country: str | None = None
    last_error: str | None = None
    success_count: int = 0
    failure_count: int = 0
    uptime: float | None = None
    consecutive_successes: int = 0
    consecutive_failures: int = 0
    score: float | None = None
    avg_latency_ms: float | None = None
    check_count: int = 0
    retired_at: str | None = None
    id: int | None = None

    @property
    def key(self) -> str:
        return f"{self.protocol}://{self.host}:{self.port}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProxyRecord:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass(slots=True)
class CheckResult:
    ok: bool
    latency_ms: float
    egress_ip: str | None = None
    egress_country: str | None = None
    error: str | None = None
    probe_url: str | None = None
    checked_at: str = field(default_factory=utc_now)

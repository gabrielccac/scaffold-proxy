from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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
    status: str = "pending"  # pending | alive | dead
    last_checked_at: str | None = None
    last_latency_ms: float | None = None
    egress_ip: str | None = None
    egress_country: str | None = None
    last_error: str | None = None
    success_count: int = 0
    failure_count: int = 0
    uptime: float | None = None

    @property
    def key(self) -> str:
        return f"{self.protocol}://{self.host}:{self.port}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProxyRecord:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

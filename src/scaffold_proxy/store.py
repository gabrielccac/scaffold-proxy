from __future__ import annotations

import json
from pathlib import Path

from scaffold_proxy.models import ProxyRecord, utc_now


class ProxyFileStore:
    """Simple JSON file store (no DB)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> list[ProxyRecord]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        items = raw.get("proxies", raw if isinstance(raw, list) else [])
        return [ProxyRecord.from_dict(item) for item in items]

    def save(self, proxies: list[ProxyRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": utc_now(),
            "count": len(proxies),
            "proxies": [p.to_dict() for p in proxies],
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def upsert(self, incoming: list[ProxyRecord]) -> list[ProxyRecord]:
        by_key = {p.key: p for p in self.load()}
        now = utc_now()
        for proxy in incoming:
            existing = by_key.get(proxy.key)
            if existing is None:
                by_key[proxy.key] = proxy
                continue
            existing.last_seen_at = now
            existing.country = proxy.country or existing.country
            existing.city = proxy.city or existing.city
            existing.anonymity = proxy.anonymity or existing.anonymity
            existing.listed_speed_ms = proxy.listed_speed_ms or existing.listed_speed_ms
            existing.protocol = proxy.protocol or existing.protocol
            existing.source = proxy.source or existing.source
        merged = sorted(by_key.values(), key=lambda p: (p.host, p.port))
        self.save(merged)
        return merged

from __future__ import annotations

import json
from pathlib import Path

from scaffold_proxy.models import ProxyRecord, utc_now


class ProxyFileStore:
    """Legacy JSON file store (import/export)."""

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

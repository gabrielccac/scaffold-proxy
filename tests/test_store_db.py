from __future__ import annotations

from pathlib import Path

from scaffold_proxy.config import Settings
from scaffold_proxy.models import CheckResult, ProxyRecord
from scaffold_proxy.store_db import SqliteProxyStore


def test_sqlite_upsert_and_revive(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    settings = Settings(database_url=f"sqlite:///{db}", score_window=5)
    store = SqliteProxyStore(settings.database_url, settings=settings)

    p = ProxyRecord(host="1.2.3.4", port=8080, protocol="http", country="US")
    inserted, refreshed, touched = store.upsert_scraped([p])
    assert inserted == 1 and refreshed == 0 and touched == 1

    rows = store.list()
    assert len(rows) == 1
    assert rows[0].status == "pending"

    # fail enough to retire
    for _ in range(settings.retire_after_failures):
        rows[0] = store.apply_check(
            rows[0],
            CheckResult(ok=False, latency_ms=100, error="boom", probe_url="x"),
            settings=settings,
        )
    assert rows[0].status == "retired"

    # seen again in scrape -> fresh pending
    inserted, refreshed, touched = store.upsert_scraped([p])
    assert refreshed == 1
    again = store.list()[0]
    assert again.status == "pending"
    assert again.consecutive_failures == 0
    assert again.check_count == settings.retire_after_failures  # history kept


def test_sqlite_score_on_success(tmp_path: Path) -> None:
    db = tmp_path / "t2.db"
    settings = Settings(database_url=f"sqlite:///{db}", fast_latency_ms=5000)
    store = SqliteProxyStore(settings.database_url, settings=settings)
    p = ProxyRecord(host="8.8.8.8", port=80, protocol="http", country="US")
    store.upsert_scraped([p])
    row = store.list()[0]
    updated = store.apply_check(
        row,
        CheckResult(
            ok=True,
            latency_ms=900,
            egress_ip="8.8.8.8",
            egress_country="US",
            probe_url="https://api.ipify.org",
        ),
        settings=settings,
    )
    assert updated.status == "alive"
    assert updated.score is not None and updated.score > 0
    assert updated.success_count == 1

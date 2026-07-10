from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Select, asc, desc, func, select
from sqlalchemy.orm import Session, sessionmaker

from scaffold_proxy.config import Settings
from scaffold_proxy.db.models import CheckRow, ProxyRow, init_db, make_session_factory
from scaffold_proxy.models import CheckResult, ProxyRecord, utc_now
from scaffold_proxy.scoring import compute_score, reset_to_fresh_fields


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    # accept ISO with or without Z
    text = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _fmt_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(microsecond=0).isoformat()


def row_to_record(row: ProxyRow) -> ProxyRecord:
    return ProxyRecord(
        id=row.id,
        host=row.host,
        port=row.port,
        protocol=row.protocol,
        source=row.source,
        country=row.country,
        city=row.city,
        anonymity=row.anonymity,
        listed_speed_ms=row.listed_speed_ms,
        first_seen_at=_fmt_dt(row.first_seen_at) or utc_now(),
        last_seen_at=_fmt_dt(row.last_seen_at) or utc_now(),
        status=row.status,
        last_checked_at=_fmt_dt(row.last_checked_at),
        last_latency_ms=row.last_latency_ms,
        egress_ip=row.egress_ip,
        egress_country=row.egress_country,
        last_error=row.last_error,
        success_count=row.success_count,
        failure_count=row.failure_count,
        uptime=row.uptime,
        consecutive_successes=row.consecutive_successes,
        consecutive_failures=row.consecutive_failures,
        score=row.score,
        avg_latency_ms=row.avg_latency_ms,
        check_count=row.check_count,
        retired_at=_fmt_dt(row.retired_at),
    )


class SqliteProxyStore:
    def __init__(self, database_url: str, settings: Settings | None = None) -> None:
        self.database_url = database_url
        self.settings = settings or Settings.from_env()
        self._session_factory, self._engine = make_session_factory(database_url)
        init_db(database_url)

    def session(self) -> Session:
        return self._session_factory()

    def count(self) -> int:
        with self.session() as s:
            return int(s.scalar(select(func.count()).select_from(ProxyRow)) or 0)

    def stats(self) -> dict[str, int]:
        with self.session() as s:
            rows = s.execute(
                select(ProxyRow.status, func.count()).group_by(ProxyRow.status)
            ).all()
        out = {status: 0 for status in ("pending", "alive", "degraded", "dead", "retired")}
        total = 0
        for status, n in rows:
            out[str(status)] = int(n)
            total += int(n)
        out["total"] = total
        return out

    def list(
        self,
        *,
        status: str | None = None,
        country: str | None = None,
        limit: int | None = None,
        order_by_score: bool = False,
    ) -> list[ProxyRecord]:
        stmt: Select = select(ProxyRow)
        if status and status != "all":
            stmt = stmt.where(ProxyRow.status == status)
        if country:
            stmt = stmt.where(ProxyRow.country == country.upper())
        if order_by_score:
            stmt = stmt.order_by(desc(ProxyRow.score).nullslast(), asc(ProxyRow.host))
        else:
            stmt = stmt.order_by(asc(ProxyRow.host), asc(ProxyRow.port))
        if limit is not None:
            stmt = stmt.limit(limit)
        with self.session() as s:
            rows = s.scalars(stmt).all()
            return [row_to_record(r) for r in rows]

    def due_for_validation(
        self,
        *,
        statuses: list[str],
        older_than_seconds: int,
        limit: int,
    ) -> list[ProxyRecord]:
        cutoff = datetime.utcnow().timestamp() - older_than_seconds
        cutoff_dt = datetime.utcfromtimestamp(max(0, cutoff))
        stmt = (
            select(ProxyRow)
            .where(ProxyRow.status.in_(statuses))
            .where(
                (ProxyRow.last_checked_at.is_(None))
                | (ProxyRow.last_checked_at <= cutoff_dt)
            )
            .order_by(ProxyRow.last_checked_at.asc().nullsfirst())
            .limit(limit)
        )
        with self.session() as s:
            return [row_to_record(r) for r in s.scalars(stmt).all()]

    def upsert_scraped(self, incoming: list[ProxyRecord]) -> tuple[int, int, int]:
        """Upsert scraped proxies.

        Returns (inserted, refreshed_fresh, touched).
        Re-seen dead/retired proxies are reset to pending (fresh).
        """
        inserted = 0
        refreshed = 0
        touched = 0
        now = datetime.utcnow()
        with self.session() as s:
            for proxy in incoming:
                row = s.scalar(
                    select(ProxyRow).where(
                        ProxyRow.host == proxy.host,
                        ProxyRow.port == proxy.port,
                        ProxyRow.protocol == proxy.protocol,
                    )
                )
                if row is None:
                    row = ProxyRow(
                        host=proxy.host,
                        port=proxy.port,
                        protocol=proxy.protocol,
                        source=proxy.source,
                        country=proxy.country,
                        city=proxy.city,
                        anonymity=proxy.anonymity,
                        listed_speed_ms=proxy.listed_speed_ms,
                        status="pending",
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                    s.add(row)
                    inserted += 1
                    touched += 1
                    continue

                row.last_seen_at = now
                row.country = proxy.country or row.country
                row.city = proxy.city or row.city
                row.anonymity = proxy.anonymity or row.anonymity
                row.listed_speed_ms = proxy.listed_speed_ms or row.listed_speed_ms
                row.source = proxy.source or row.source
                touched += 1

                if row.status in ("dead", "retired"):
                    for key, value in reset_to_fresh_fields().items():
                        setattr(row, key, value)
                    refreshed += 1
            s.commit()
        return inserted, refreshed, touched

    def apply_check(
        self,
        proxy: ProxyRecord,
        result: CheckResult,
        *,
        settings: Settings | None = None,
    ) -> ProxyRecord:
        settings = settings or self.settings
        with self.session() as s:
            row = s.get(ProxyRow, proxy.id) if proxy.id is not None else None
            if row is None:
                row = s.scalar(
                    select(ProxyRow).where(
                        ProxyRow.host == proxy.host,
                        ProxyRow.port == proxy.port,
                        ProxyRow.protocol == proxy.protocol,
                    )
                )
            if row is None:
                raise ValueError(f"proxy not found: {proxy.key}")

            checked_at = _parse_dt(result.checked_at) or datetime.utcnow()
            s.add(
                CheckRow(
                    proxy_id=row.id,
                    checked_at=checked_at,
                    ok=result.ok,
                    latency_ms=result.latency_ms,
                    egress_ip=result.egress_ip,
                    egress_country=result.egress_country,
                    error=result.error,
                    probe_url=result.probe_url,
                )
            )

            row.last_checked_at = checked_at
            row.last_latency_ms = result.latency_ms
            row.check_count = (row.check_count or 0) + 1
            if result.egress_ip:
                row.egress_ip = result.egress_ip
            if result.egress_country:
                row.egress_country = result.egress_country

            if result.ok:
                row.success_count = (row.success_count or 0) + 1
                row.consecutive_successes = (row.consecutive_successes or 0) + 1
                row.consecutive_failures = 0
                row.last_error = None
            else:
                row.failure_count = (row.failure_count or 0) + 1
                row.consecutive_failures = (row.consecutive_failures or 0) + 1
                row.consecutive_successes = 0
                row.last_error = (result.error or "failed")[:500]

            total = (row.success_count or 0) + (row.failure_count or 0)
            row.uptime = (row.success_count / total) if total else None

            s.flush()

            # Trim history to score_window * 2 (keep a bit extra)
            keep = max(settings.score_window * 2, settings.score_window)
            old_ids = list(
                s.scalars(
                    select(CheckRow.id)
                    .where(CheckRow.proxy_id == row.id)
                    .order_by(desc(CheckRow.checked_at), desc(CheckRow.id))
                    .offset(keep)
                ).all()
            )
            if old_ids:
                from sqlalchemy import delete

                s.execute(delete(CheckRow).where(CheckRow.id.in_(old_ids)))

            recent = list(
                s.scalars(
                    select(CheckRow)
                    .where(CheckRow.proxy_id == row.id)
                    .order_by(desc(CheckRow.checked_at), desc(CheckRow.id))
                    .limit(settings.score_window)
                ).all()
            )
            # chronological for scoring
            recent.reverse()
            breakdown = compute_score(
                recent_oks=[c.ok for c in recent],
                recent_latencies=[c.latency_ms for c in recent],
                consecutive_successes=row.consecutive_successes,
                consecutive_failures=row.consecutive_failures,
                last_ok=result.ok,
                last_latency_ms=result.latency_ms,
                settings=settings,
            )
            row.score = breakdown.score
            row.avg_latency_ms = breakdown.avg_latency_ms
            row.status = breakdown.status
            if breakdown.status == "retired":
                row.retired_at = checked_at
            elif row.retired_at is not None and breakdown.status != "retired":
                row.retired_at = None

            s.commit()
            s.refresh(row)
            return row_to_record(row)

    def import_records(self, records: list[ProxyRecord]) -> int:
        """Import domain records (e.g. from JSON) without wiping history."""
        inserted, refreshed, touched = self.upsert_scraped(records)
        # Also copy validation stats if present on incoming pending-less imports
        with self.session() as s:
            for proxy in records:
                row = s.scalar(
                    select(ProxyRow).where(
                        ProxyRow.host == proxy.host,
                        ProxyRow.port == proxy.port,
                        ProxyRow.protocol == proxy.protocol,
                    )
                )
                if row is None:
                    continue
                # Only seed counters if never checked in DB
                if row.check_count:
                    continue
                if proxy.check_count or proxy.success_count or proxy.failure_count:
                    row.status = proxy.status if proxy.status in (
                        "pending",
                        "alive",
                        "degraded",
                        "dead",
                        "retired",
                    ) else "pending"
                    row.success_count = proxy.success_count
                    row.failure_count = proxy.failure_count
                    row.uptime = proxy.uptime
                    row.last_latency_ms = proxy.last_latency_ms
                    row.egress_ip = proxy.egress_ip
                    row.egress_country = proxy.egress_country
                    row.last_error = proxy.last_error
                    row.last_checked_at = _parse_dt(proxy.last_checked_at)
                    row.score = proxy.score
                    row.avg_latency_ms = proxy.avg_latency_ms
                    row.check_count = proxy.check_count
                    row.consecutive_successes = proxy.consecutive_successes
                    row.consecutive_failures = proxy.consecutive_failures
            s.commit()
        return touched

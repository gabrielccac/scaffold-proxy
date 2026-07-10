from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable
from datetime import timedelta

from wreq import Client, Emulation, Proxy

from scaffold_proxy.config import Settings, probe_for_country
from scaffold_proxy.models import CheckResult, ProxyRecord, utc_now
from scaffold_proxy.store_db import SqliteProxyStore

ProgressCallback = Callable[[int, int, ProxyRecord], None]

_IP_ONLY_RE = re.compile(
    r"^\s*(\d{1,3}(?:\.\d{1,3}){3}|[0-9a-fA-F:]+)\s*$"
)


def _emulation(name: str):
    return getattr(Emulation, name)


def _proxy_url(proxy: ProxyRecord) -> str:
    if proxy.protocol.startswith("socks5"):
        return f"socks5h://{proxy.host}:{proxy.port}"
    if proxy.protocol.startswith("socks4"):
        return f"socks4a://{proxy.host}:{proxy.port}"
    return f"http://{proxy.host}:{proxy.port}"


def _extract_probe(body: str) -> tuple[str | None, str | None]:
    text = body.strip()
    if not text:
        return None, None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        m = _IP_ONLY_RE.match(text)
        return (m.group(1) if m else None, None)

    if isinstance(payload, str):
        m = _IP_ONLY_RE.match(payload.strip())
        return (m.group(1) if m else payload.strip() or None, None)
    if not isinstance(payload, dict):
        return None, None

    ip = payload.get("ip") or payload.get("query") or payload.get("origin")
    if isinstance(ip, str) and "," in ip:
        ip = ip.split(",")[0].strip()
    country = (
        payload.get("country_code")
        or payload.get("countryCode")
        or payload.get("country")
    )
    return (
        str(ip).strip() if ip else None,
        str(country).strip().upper() if country else None,
    )


async def probe_proxy(
    proxy: ProxyRecord,
    *,
    settings: Settings,
    client: Client,
    probe_url: str | None = None,
    expect_country: str | None = None,
) -> CheckResult:
    if probe_url is None or expect_country is None:
        auto_url, auto_expect = probe_for_country(proxy.country)
        probe_url = probe_url if probe_url is not None else auto_url
        expect_country = expect_country if expect_country is not None else auto_expect

    started = time.perf_counter()
    try:
        response = await client.get(
            probe_url,
            proxy=Proxy.all(_proxy_url(proxy)),
            timeout=timedelta(seconds=settings.validate_timeout_seconds),
        )
        status = response.status.as_int()
        body = await response.text()
        latency_ms = (time.perf_counter() - started) * 1000

        if status != 200:
            return CheckResult(
                ok=False,
                latency_ms=latency_ms,
                error=f"http_{status}",
                probe_url=probe_url,
            )

        egress_ip, egress_country = _extract_probe(body)
        if not egress_ip:
            return CheckResult(
                ok=False,
                latency_ms=latency_ms,
                error="missing_ip",
                probe_url=probe_url,
            )

        if expect_country:
            if (egress_country or "").upper() != expect_country.upper():
                return CheckResult(
                    ok=False,
                    latency_ms=latency_ms,
                    egress_ip=egress_ip,
                    egress_country=egress_country,
                    error=f"country_mismatch:{egress_country}",
                    probe_url=probe_url,
                )

        return CheckResult(
            ok=True,
            latency_ms=latency_ms,
            egress_ip=egress_ip,
            egress_country=egress_country,
            probe_url=probe_url,
        )
    except Exception as exc:  # noqa: BLE001
        latency_ms = (time.perf_counter() - started) * 1000
        return CheckResult(
            ok=False,
            latency_ms=latency_ms,
            error=f"{type(exc).__name__}:{exc}"[:500],
            probe_url=probe_url,
        )


async def validate_many(
    proxies: list[ProxyRecord],
    *,
    store: SqliteProxyStore,
    settings: Settings | None = None,
    on_progress: ProgressCallback | None = None,
    use_settings_probe: bool = False,
) -> list[ProxyRecord]:
    settings = settings or Settings.from_env()
    if not proxies:
        return []

    concurrency = max(1, settings.validate_concurrency)
    sem = asyncio.Semaphore(concurrency)
    total = len(proxies)
    done = 0
    lock = asyncio.Lock()

    client = Client(
        emulation=_emulation(settings.emulation),
        timeout=timedelta(seconds=settings.validate_timeout_seconds),
    )

    async def _run(proxy: ProxyRecord) -> ProxyRecord:
        nonlocal done
        async with sem:
            if use_settings_probe:
                result = await probe_proxy(
                    proxy,
                    settings=settings,
                    client=client,
                    probe_url=settings.probe_url,
                    expect_country=settings.expect_country,
                )
            else:
                result = await probe_proxy(proxy, settings=settings, client=client)
            updated = await asyncio.to_thread(
                store.apply_check, proxy, result, settings=settings
            )
        if on_progress is not None:
            async with lock:
                done += 1
                on_progress(done, total, updated)
        return updated

    try:
        return list(await asyncio.gather(*[_run(p) for p in proxies]))
    finally:
        close = client.close()
        if asyncio.iscoroutine(close):
            await close

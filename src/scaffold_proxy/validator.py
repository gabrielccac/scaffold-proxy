from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from datetime import timedelta

from wreq import Client, Emulation, Proxy

from scaffold_proxy.config import Settings
from scaffold_proxy.models import ProxyRecord, utc_now

ProgressCallback = Callable[[int, int, ProxyRecord], None]


def _emulation(name: str):
    return getattr(Emulation, name)


def _proxy_url(proxy: ProxyRecord) -> str:
    # Prefer remote DNS for SOCKS when available.
    if proxy.protocol.startswith("socks5"):
        return f"socks5h://{proxy.host}:{proxy.port}"
    if proxy.protocol.startswith("socks4"):
        return f"socks4a://{proxy.host}:{proxy.port}"
    return f"http://{proxy.host}:{proxy.port}"


import re

_IP_ONLY_RE = re.compile(
    r"^\s*(\d{1,3}(?:\.\d{1,3}){3}|[0-9a-fA-F:]+)\s*$"
)


def _extract_probe(body: str) -> tuple[str | None, str | None]:
    """Parse probe body as JSON object or plain-text IP (e.g. ipify)."""
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
        # httpbin may return "client, proxy"
        ip = ip.split(",")[0].strip()
    country = (
        payload.get("country_code")
        or payload.get("countryCode")
        or payload.get("country")
    )
    if isinstance(country, str) and len(country) != 2:
        # prefer ISO code fields; full country name is still usable if that's all we have
        pass
    return (
        str(ip).strip() if ip else None,
        str(country).strip().upper() if country else None,
    )


async def validate_one(
    proxy: ProxyRecord,
    *,
    settings: Settings,
    client: Client,
) -> ProxyRecord:
    started = time.perf_counter()
    try:
        response = await client.get(
            settings.probe_url,
            proxy=Proxy.all(_proxy_url(proxy)),
            timeout=timedelta(seconds=settings.validate_timeout_seconds),
        )
        status = response.status.as_int()
        body = await response.text()
        latency_ms = (time.perf_counter() - started) * 1000

        if status != 200:
            return _mark_dead(proxy, f"http_{status}", latency_ms)

        egress_ip, egress_country = _extract_probe(body)
        if not egress_ip:
            return _mark_dead(proxy, "missing_ip", latency_ms)

        if settings.expect_country:
            if (egress_country or "").upper() != settings.expect_country.upper():
                return _mark_dead(
                    proxy,
                    f"country_mismatch:{egress_country}",
                    latency_ms,
                    egress_ip=egress_ip,
                    egress_country=egress_country,
                )

        return _mark_alive(
            proxy,
            latency_ms=latency_ms,
            egress_ip=egress_ip,
            egress_country=egress_country,
        )
    except Exception as exc:  # noqa: BLE001 - classify proxy failures
        latency_ms = (time.perf_counter() - started) * 1000
        return _mark_dead(proxy, f"{type(exc).__name__}:{exc}", latency_ms)


def _recompute_uptime(proxy: ProxyRecord) -> None:
    total = proxy.success_count + proxy.failure_count
    proxy.uptime = (proxy.success_count / total) if total else None


def _mark_alive(
    proxy: ProxyRecord,
    *,
    latency_ms: float,
    egress_ip: str | None,
    egress_country: str | None,
) -> ProxyRecord:
    proxy.status = "alive"
    proxy.last_checked_at = utc_now()
    proxy.last_latency_ms = round(latency_ms, 1)
    proxy.egress_ip = egress_ip
    proxy.egress_country = egress_country
    proxy.last_error = None
    proxy.success_count += 1
    _recompute_uptime(proxy)
    return proxy


def _mark_dead(
    proxy: ProxyRecord,
    error: str,
    latency_ms: float,
    *,
    egress_ip: str | None = None,
    egress_country: str | None = None,
) -> ProxyRecord:
    proxy.status = "dead"
    proxy.last_checked_at = utc_now()
    proxy.last_latency_ms = round(latency_ms, 1)
    proxy.last_error = error[:500]
    if egress_ip:
        proxy.egress_ip = egress_ip
    if egress_country:
        proxy.egress_country = egress_country
    proxy.failure_count += 1
    _recompute_uptime(proxy)
    return proxy


async def validate_many(
    proxies: list[ProxyRecord],
    *,
    settings: Settings | None = None,
    on_progress: ProgressCallback | None = None,
) -> list[ProxyRecord]:
    """Validate many proxies concurrently.

    Uses one shared wreq client and per-request ``proxy=`` so we can fan out
    aggressively without paying client-construction cost per proxy.
    Concurrency is capped by ``settings.validate_concurrency``.
    """
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
            result = await validate_one(proxy, settings=settings, client=client)
        if on_progress is not None:
            async with lock:
                done += 1
                on_progress(done, total, result)
        return result

    try:
        return list(await asyncio.gather(*[_run(p) for p in proxies]))
    finally:
        close = client.close()
        if asyncio.iscoroutine(close):
            await close

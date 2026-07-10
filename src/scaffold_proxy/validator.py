from __future__ import annotations

import asyncio
import json
import time
from datetime import timedelta

from wreq import Client, Emulation, Proxy

from scaffold_proxy.config import Settings
from scaffold_proxy.models import ProxyRecord, utc_now


def _emulation(name: str):
    return getattr(Emulation, name)


def _proxy_url(proxy: ProxyRecord) -> str:
    # Prefer remote DNS for SOCKS when available.
    if proxy.protocol.startswith("socks5"):
        return f"socks5h://{proxy.host}:{proxy.port}"
    if proxy.protocol.startswith("socks4"):
        return f"socks4a://{proxy.host}:{proxy.port}"
    return f"http://{proxy.host}:{proxy.port}"


def _extract_probe(payload: dict) -> tuple[str | None, str | None]:
    ip = payload.get("ip") or payload.get("query") or payload.get("origin")
    country = (
        payload.get("country")
        or payload.get("country_code")
        or payload.get("countryCode")
    )
    if isinstance(country, str) and len(country) > 2:
        # meuip returns "BR" already; ipwho may return full name — leave as-is
        pass
    return (str(ip) if ip else None, str(country).upper() if country else None)


async def validate_one(
    proxy: ProxyRecord,
    *,
    settings: Settings,
    client: Client | None = None,
) -> ProxyRecord:
    owns_client = client is None
    if client is None:
        client = Client(
            emulation=_emulation(settings.emulation),
            timeout=timedelta(seconds=settings.validate_timeout_seconds),
        )

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

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return _mark_dead(proxy, "invalid_json", latency_ms)

        egress_ip, egress_country = _extract_probe(payload)
        if not egress_ip:
            return _mark_dead(proxy, "missing_ip", latency_ms)

        country_ok = True
        if settings.expect_country:
            country_ok = (egress_country or "").upper() == settings.expect_country.upper()

        if not country_ok:
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
    finally:
        if owns_client:
            close = client.close()
            if asyncio.iscoroutine(close):
                await close


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
) -> list[ProxyRecord]:
    settings = settings or Settings.from_env()
    sem = asyncio.Semaphore(settings.validate_concurrency)

    async def _run(proxy: ProxyRecord) -> ProxyRecord:
        async with sem:
            # Fresh client per proxy avoids sticky proxy/connection pool issues.
            return await validate_one(proxy, settings=settings)

    return list(await asyncio.gather(*[_run(p) for p in proxies]))

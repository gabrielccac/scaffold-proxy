from __future__ import annotations

import asyncio
from datetime import timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from wreq import Client, Emulation

from scaffold_proxy.config import Settings
from scaffold_proxy.models import ProxyRecord
from scaffold_proxy.parse import is_challenge_html, parse_proxy_table


def _with_page(url: str, page: int) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["page"] = str(page)
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def _emulation(name: str):
    if not hasattr(Emulation, name):
        raise ValueError(f"Unknown wreq emulation: {name}")
    return getattr(Emulation, name)


async def scrape_freeproxy_world(settings: Settings | None = None) -> list[ProxyRecord]:
    settings = settings or Settings.from_env()
    client = Client(
        emulation=_emulation(settings.emulation),
        cookie_store=True,
        timeout=timedelta(seconds=settings.scrape_timeout_seconds),
    )
    collected: list[ProxyRecord] = []
    seen: set[str] = set()

    try:
        for page in range(1, settings.max_pages + 1):
            url = settings.scrape_url if page == 1 else _with_page(settings.scrape_url, page)
            response = await client.get(url)
            status = response.status.as_int()
            html = await response.text()

            if is_challenge_html(html, status):
                raise RuntimeError(
                    f"Cloudflare challenge on page {page} "
                    f"(status={status}, emulation={settings.emulation})"
                )
            if status != 200:
                raise RuntimeError(f"Unexpected status {status} on page {page}")

            page_proxies = parse_proxy_table(html, source="freeproxy.world")
            if not page_proxies:
                break

            new_count = 0
            for proxy in page_proxies:
                if proxy.country is None and "country=BR" in settings.scrape_url:
                    proxy.country = "BR"
                if proxy.key in seen:
                    continue
                seen.add(proxy.key)
                collected.append(proxy)
                new_count += 1

            if new_count == 0:
                break

            if page < settings.max_pages:
                await asyncio.sleep(settings.page_delay_seconds)
    finally:
        close = client.close()
        if asyncio.iscoroutine(close):
            await close

    return collected

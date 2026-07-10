from __future__ import annotations

import re

from scaffold_proxy.models import ProxyRecord

_ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.I | re.S)
_IP_RE = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})")
_PORT_RE = re.compile(r'href="/\?port=(\d+)"')
_TYPE_RE = re.compile(
    r'class="badge[^"]*"[^>]*>\s*(http|https|socks4|socks5)\s*<', re.I
)
_ANON_RE = re.compile(r'anonymity=\d+"[^>]*>\s*([^<]+)')
_CITY_RE = re.compile(r'class="text-truncate" title="([^"]+)"')
_SPEED_RE = re.compile(r"(\d+)\s*ms", re.I)
_COUNTRY_RE = re.compile(r'href="/\?country=([A-Z]{2})"', re.I)
_CHALLENGE_MARKERS = ("just a moment", "cf-browser-verification", "challenge-platform")


def is_challenge_html(html: str, status: int) -> bool:
    if status in (403, 503, 429) and "IP Address" not in html:
        return True
    low = html.lower()
    return any(m in low for m in _CHALLENGE_MARKERS) and "IP Address" not in html


def parse_proxy_table(html: str, *, source: str = "freeproxy.world") -> list[ProxyRecord]:
    proxies: list[ProxyRecord] = []
    seen: set[str] = set()

    for block in _ROW_RE.findall(html):
        ip_m = _IP_RE.search(block)
        port_m = _PORT_RE.search(block)
        if not ip_m or not port_m:
            continue

        type_m = _TYPE_RE.search(block)
        protocol = (type_m.group(1) if type_m else "http").lower()
        anon_m = _ANON_RE.search(block)
        city_m = _CITY_RE.search(block)
        speed_m = _SPEED_RE.search(block)
        country_m = _COUNTRY_RE.search(block)

        record = ProxyRecord(
            host=ip_m.group(1),
            port=int(port_m.group(1)),
            protocol=protocol,
            source=source,
            country=(country_m.group(1).upper() if country_m else None),
            city=(city_m.group(1) if city_m else None),
            anonymity=(anon_m.group(1).strip() if anon_m else None),
            listed_speed_ms=(int(speed_m.group(1)) if speed_m else None),
        )
        if record.key in seen:
            continue
        seen.add(record.key)
        proxies.append(record)

    return proxies

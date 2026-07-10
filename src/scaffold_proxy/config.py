from __future__ import annotations

import os
from dataclasses import dataclass, fields
from urllib.parse import urlencode


IPIFY_PROBE_URL = "https://api.ipify.org"
MEUIP_PROBE_URL = "https://meuip.martins.eng.br/all.json"


def freeproxy_world_url(country: str = "BR") -> str:
    query = urlencode(
        {
            "type": "",
            "anonymity": "",
            "country": country.upper(),
            "speed": "",
            "port": "",
        }
    )
    return f"https://www.freeproxy.world/?{query}"


@dataclass(frozen=True, slots=True)
class Settings:
    country: str = "BR"
    scrape_url: str = freeproxy_world_url("BR")
    emulation: str = "Chrome147"
    max_pages: int = 6
    # freeproxy.world serves 50 rows on a full page; shorter => last page.
    page_size: int = 50
    page_delay_seconds: float = 1.0
    proxies_file: str = "data/proxies.json"
    probe_url: str = MEUIP_PROBE_URL
    expect_country: str = "BR"
    validate_timeout_seconds: float = 8.0
    # High fan-out: most free proxies die on connect; bound with a semaphore.
    validate_concurrency: int = 100
    scrape_timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> Settings:
        defaults = {f.name: f.default for f in fields(cls)}
        country = os.getenv("COUNTRY", str(defaults["country"])).upper() or "BR"

        scrape_url = os.getenv("SCRAPE_URL") or freeproxy_world_url(country)

        if "PROBE_URL" in os.environ:
            probe_url = os.environ["PROBE_URL"]
        elif country == "BR":
            probe_url = MEUIP_PROBE_URL
        else:
            probe_url = IPIFY_PROBE_URL

        if "EXPECT_COUNTRY" in os.environ:
            expect_country = os.environ["EXPECT_COUNTRY"].upper()
        elif country == "BR":
            expect_country = "BR"
        else:
            expect_country = ""

        def env(name: str, key: str) -> str:
            return os.getenv(name, str(defaults[key]))

        return cls(
            country=country,
            scrape_url=scrape_url,
            emulation=env("WREQ_EMULATION", "emulation"),
            max_pages=int(env("MAX_PAGES", "max_pages")),
            page_size=int(env("PAGE_SIZE", "page_size")),
            page_delay_seconds=float(env("PAGE_DELAY_SECONDS", "page_delay_seconds")),
            proxies_file=env("PROXIES_FILE", "proxies_file"),
            probe_url=probe_url,
            expect_country=expect_country,
            validate_timeout_seconds=float(
                env("VALIDATE_TIMEOUT_SECONDS", "validate_timeout_seconds")
            ),
            validate_concurrency=int(env("VALIDATE_CONCURRENCY", "validate_concurrency")),
            scrape_timeout_seconds=float(
                env("SCRAPE_TIMEOUT_SECONDS", "scrape_timeout_seconds")
            ),
        )


def apply_country(settings: Settings, country: str) -> Settings:
    """Retarget scrape URL / default probe for a country code."""
    from dataclasses import replace

    country = country.upper()
    updates: dict = {
        "country": country,
        "scrape_url": freeproxy_world_url(country),
    }
    if country == "BR":
        updates["probe_url"] = MEUIP_PROBE_URL
        updates["expect_country"] = "BR"
    else:
        updates["probe_url"] = IPIFY_PROBE_URL
        updates["expect_country"] = ""
    return replace(settings, **updates)

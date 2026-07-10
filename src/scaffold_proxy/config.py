from __future__ import annotations

import os
from dataclasses import dataclass, fields, replace
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
    page_size: int = 50
    page_delay_seconds: float = 1.0
    proxies_file: str = "data/proxies.json"
    database_url: str = "sqlite:///./data/proxies.db"
    probe_url: str = MEUIP_PROBE_URL
    expect_country: str = "BR"
    validate_timeout_seconds: float = 8.0
    validate_concurrency: int = 100
    scrape_timeout_seconds: float = 30.0
    # Scoring / status
    score_window: int = 20
    fast_latency_ms: float = 5000.0
    dead_after_failures: int = 3
    retire_after_failures: int = 10
    # Worker intervals (seconds)
    countries: str = "BR"
    scrape_interval_seconds: int = 900
    validate_pending_interval_seconds: int = 60
    validate_alive_interval_seconds: int = 600
    validate_dead_interval_seconds: int = 1800
    validate_batch_size: int = 200

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
            database_url=env("DATABASE_URL", "database_url"),
            probe_url=probe_url,
            expect_country=expect_country,
            validate_timeout_seconds=float(
                env("VALIDATE_TIMEOUT_SECONDS", "validate_timeout_seconds")
            ),
            validate_concurrency=int(env("VALIDATE_CONCURRENCY", "validate_concurrency")),
            scrape_timeout_seconds=float(
                env("SCRAPE_TIMEOUT_SECONDS", "scrape_timeout_seconds")
            ),
            score_window=int(env("SCORE_WINDOW", "score_window")),
            fast_latency_ms=float(env("FAST_LATENCY_MS", "fast_latency_ms")),
            dead_after_failures=int(env("DEAD_AFTER_FAILURES", "dead_after_failures")),
            retire_after_failures=int(
                env("RETIRE_AFTER_FAILURES", "retire_after_failures")
            ),
            countries=env("COUNTRIES", "countries"),
            scrape_interval_seconds=int(
                env("SCRAPE_INTERVAL_SECONDS", "scrape_interval_seconds")
            ),
            validate_pending_interval_seconds=int(
                env(
                    "VALIDATE_PENDING_INTERVAL_SECONDS",
                    "validate_pending_interval_seconds",
                )
            ),
            validate_alive_interval_seconds=int(
                env("VALIDATE_ALIVE_INTERVAL_SECONDS", "validate_alive_interval_seconds")
            ),
            validate_dead_interval_seconds=int(
                env("VALIDATE_DEAD_INTERVAL_SECONDS", "validate_dead_interval_seconds")
            ),
            validate_batch_size=int(env("VALIDATE_BATCH_SIZE", "validate_batch_size")),
        )


def apply_country(settings: Settings, country: str) -> Settings:
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


def parse_countries(value: str | None) -> list[str]:
    """Parse 'BR,US,CA' or 'BR US CA' into unique uppercase codes."""
    if not value:
        return []
    parts = [p.strip().upper() for p in value.replace(";", ",").replace(" ", ",").split(",")]
    out: list[str] = []
    for part in parts:
        if part and part not in out:
            out.append(part)
    return out


def probe_for_country(country: str | None) -> tuple[str, str]:
    """Return (probe_url, expect_country) for a proxy's country."""
    if (country or "").upper() == "BR":
        return MEUIP_PROBE_URL, "BR"
    return IPIFY_PROBE_URL, ""

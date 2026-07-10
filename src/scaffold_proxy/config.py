from __future__ import annotations

import os
from dataclasses import dataclass, fields


@dataclass(frozen=True, slots=True)
class Settings:
    scrape_url: str = (
        "https://www.freeproxy.world/"
        "?type=&anonymity=&country=BR&speed=&port="
    )
    emulation: str = "Chrome147"
    max_pages: int = 6
    page_delay_seconds: float = 1.0
    proxies_file: str = "data/proxies.json"
    probe_url: str = "https://meuip.martins.eng.br/all.json"
    expect_country: str = "BR"
    validate_timeout_seconds: float = 8.0
    # High fan-out: most free proxies die on connect; bound with a semaphore.
    validate_concurrency: int = 100
    scrape_timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> Settings:
        defaults = {f.name: f.default for f in fields(cls)}

        def env(name: str, key: str) -> str:
            return os.getenv(name, str(defaults[key]))

        return cls(
            scrape_url=env("SCRAPE_URL", "scrape_url"),
            emulation=env("WREQ_EMULATION", "emulation"),
            max_pages=int(env("MAX_PAGES", "max_pages")),
            page_delay_seconds=float(env("PAGE_DELAY_SECONDS", "page_delay_seconds")),
            proxies_file=env("PROXIES_FILE", "proxies_file"),
            probe_url=env("PROBE_URL", "probe_url"),
            expect_country=os.getenv(
                "EXPECT_COUNTRY", str(defaults["expect_country"])
            ).upper(),
            validate_timeout_seconds=float(
                env("VALIDATE_TIMEOUT_SECONDS", "validate_timeout_seconds")
            ),
            validate_concurrency=int(env("VALIDATE_CONCURRENCY", "validate_concurrency")),
            scrape_timeout_seconds=float(
                env("SCRAPE_TIMEOUT_SECONDS", "scrape_timeout_seconds")
            ),
        )

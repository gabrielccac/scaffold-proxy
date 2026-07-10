from __future__ import annotations

import os
from dataclasses import dataclass


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
    validate_timeout_seconds: float = 10.0
    validate_concurrency: int = 40
    scrape_timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> Settings:
        def getenv(name: str, default: str) -> str:
            return os.getenv(name, default)

        return cls(
            scrape_url=getenv("SCRAPE_URL", cls.scrape_url),
            emulation=getenv("WREQ_EMULATION", cls.emulation),
            max_pages=int(getenv("MAX_PAGES", str(cls.max_pages))),
            page_delay_seconds=float(
                getenv("PAGE_DELAY_SECONDS", str(cls.page_delay_seconds))
            ),
            proxies_file=getenv("PROXIES_FILE", cls.proxies_file),
            probe_url=getenv("PROBE_URL", cls.probe_url),
            expect_country=getenv("EXPECT_COUNTRY", cls.expect_country).upper(),
            validate_timeout_seconds=float(
                getenv("VALIDATE_TIMEOUT_SECONDS", str(cls.validate_timeout_seconds))
            ),
            validate_concurrency=int(
                getenv("VALIDATE_CONCURRENCY", str(cls.validate_concurrency))
            ),
            scrape_timeout_seconds=float(
                getenv("SCRAPE_TIMEOUT_SECONDS", str(cls.scrape_timeout_seconds))
            ),
        )

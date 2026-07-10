from __future__ import annotations

import asyncio
import logging
from dataclasses import replace

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from scaffold_proxy.collectors.freeproxy_world import scrape_freeproxy_world
from scaffold_proxy.config import Settings, apply_country
from scaffold_proxy.store_db import SqliteProxyStore
from scaffold_proxy.validator import validate_many

log = logging.getLogger("scaffold_proxy.worker")


class ProxyWorker:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self.store = SqliteProxyStore(self.settings.database_url, settings=self.settings)
        self.scheduler = AsyncIOScheduler()

    def _countries(self) -> list[str]:
        return [
            c.strip().upper()
            for c in self.settings.countries.split(",")
            if c.strip()
        ]

    async def job_scrape(self) -> None:
        for country in self._countries():
            settings = apply_country(self.settings, country)
            log.info("scrape start country=%s", country)
            try:
                proxies = await scrape_freeproxy_world(settings)
                inserted, refreshed, touched = await asyncio.to_thread(
                    self.store.upsert_scraped, proxies
                )
                log.info(
                    "scrape done country=%s scraped=%s inserted=%s refreshed=%s touched=%s",
                    country,
                    len(proxies),
                    inserted,
                    refreshed,
                    touched,
                )
            except Exception:
                log.exception("scrape failed country=%s", country)

    async def _validate_statuses(
        self,
        statuses: list[str],
        older_than_seconds: int,
        label: str,
    ) -> None:
        proxies = await asyncio.to_thread(
            self.store.due_for_validation,
            statuses=statuses,
            older_than_seconds=older_than_seconds,
            limit=self.settings.validate_batch_size,
        )
        if not proxies:
            log.info("validate %s: nothing due", label)
            return
        log.info("validate %s: checking %s", label, len(proxies))
        checked = await validate_many(proxies, store=self.store, settings=self.settings)
        alive = sum(1 for p in checked if p.status == "alive")
        degraded = sum(1 for p in checked if p.status == "degraded")
        dead = sum(1 for p in checked if p.status in ("dead", "retired"))
        log.info(
            "validate %s done checked=%s alive=%s degraded=%s dead/retired=%s",
            label,
            len(checked),
            alive,
            degraded,
            dead,
        )

    async def job_validate_pending(self) -> None:
        await self._validate_statuses(["pending"], older_than_seconds=0, label="pending")

    async def job_validate_alive(self) -> None:
        await self._validate_statuses(
            ["alive", "degraded"],
            older_than_seconds=self.settings.validate_alive_interval_seconds,
            label="alive/degraded",
        )

    async def job_validate_dead(self) -> None:
        await self._validate_statuses(
            ["dead"],
            older_than_seconds=self.settings.validate_dead_interval_seconds,
            label="dead",
        )

    def setup(self) -> None:
        s = self.settings
        self.scheduler.add_job(
            self.job_scrape,
            "interval",
            seconds=s.scrape_interval_seconds,
            id="scrape",
        )
        self.scheduler.add_job(
            self.job_validate_pending,
            "interval",
            seconds=s.validate_pending_interval_seconds,
            id="validate_pending",
        )
        self.scheduler.add_job(
            self.job_validate_alive,
            "interval",
            seconds=s.validate_alive_interval_seconds,
            id="validate_alive",
        )
        self.scheduler.add_job(
            self.job_validate_dead,
            "interval",
            seconds=s.validate_dead_interval_seconds,
            id="validate_dead",
        )

    async def run(self, *, run_scrape_first: bool = True) -> None:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        self.setup()
        self.scheduler.start()
        log.info(
            "worker started countries=%s db=%s scrape=%ss pending=%ss alive=%ss dead=%ss",
            self._countries(),
            self.settings.database_url,
            self.settings.scrape_interval_seconds,
            self.settings.validate_pending_interval_seconds,
            self.settings.validate_alive_interval_seconds,
            self.settings.validate_dead_interval_seconds,
        )
        if run_scrape_first:
            await self.job_scrape()
            await self.job_validate_pending()
        try:
            while True:
                await asyncio.sleep(3600)
        except (KeyboardInterrupt, SystemExit):
            log.info("worker stopping")
            self.scheduler.shutdown(wait=False)

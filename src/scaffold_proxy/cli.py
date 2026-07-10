from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import replace

from scaffold_proxy.collectors.freeproxy_world import scrape_freeproxy_world
from scaffold_proxy.config import Settings, apply_country, parse_countries
from scaffold_proxy.db.models import init_db
from scaffold_proxy.store import ProxyFileStore
from scaffold_proxy.store_db import SqliteProxyStore
from scaffold_proxy.validator import validate_many
from scaffold_proxy.worker import ProxyWorker


def _add_country_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--country",
        type=str,
        default=None,
        help="ISO country code(s), comma-separated (e.g. BR,US,CA). "
        "Non-BR defaults probe to ipify with no country check.",
    )
    parser.add_argument(
        "--countries",
        type=str,
        default=None,
        help="Alias for --country (comma-separated list).",
    )
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument(
        "--page-size",
        type=int,
        default=None,
        help="Full-page row count; shorter page ends pagination (default: 50)",
    )
    parser.add_argument("--probe-url", type=str, default=None)
    parser.add_argument(
        "--expect-country",
        type=str,
        default=None,
        help="Require probe country code (empty string disables).",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scaffold-proxy",
        description="Collect, persist, score, and validate free proxies",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scrape = sub.add_parser("scrape", help="Scrape freeproxy.world into SQLite")
    _add_country_args(scrape)

    validate = sub.add_parser("validate", help="Validate proxies from SQLite")
    validate.add_argument("--limit", type=int, default=None)
    validate.add_argument("--concurrency", type=int, default=None)
    validate.add_argument("--probe-url", type=str, default=None)
    validate.add_argument("--expect-country", type=str, default=None)
    validate.add_argument(
        "--country",
        type=str,
        default=None,
        help="Filter by country code(s), comma-separated",
    )
    validate.add_argument(
        "--countries",
        type=str,
        default=None,
        help="Alias for --country",
    )
    validate.add_argument(
        "--status",
        choices=["pending", "alive", "degraded", "dead", "retired", "all"],
        default="pending",
    )
    validate.add_argument(
        "--use-settings-probe",
        action="store_true",
        help="Force settings probe/expect instead of per-proxy country defaults",
    )

    run = sub.add_parser("run", help="Scrape then validate pending")
    _add_country_args(run)
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--concurrency", type=int, default=None)

    stats = sub.add_parser("stats", help="Show pool status counts / top scores")
    stats.add_argument("--top", type=int, default=10)

    worker = sub.add_parser("worker", help="Run in-process scrape/validate scheduler")
    worker.add_argument(
        "--no-initial-scrape",
        action="store_true",
        help="Do not scrape/validate immediately on startup",
    )
    worker.add_argument(
        "--country",
        type=str,
        default=None,
        help="Comma-separated countries (overrides COUNTRIES)",
    )
    worker.add_argument(
        "--countries",
        type=str,
        default=None,
        help="Alias for --country",
    )

    sub.add_parser("init-db", help="Create SQLite tables")

    import_json = sub.add_parser("import-json", help="Import a legacy JSON proxy file")
    import_json.add_argument("path", type=str)

    export_json = sub.add_parser("export-json", help="Export DB pool to JSON")
    export_json.add_argument("--out", type=str, default="data/proxies_export.json")
    export_json.add_argument("--status", type=str, default="all")

    return parser


def _store(settings: Settings) -> SqliteProxyStore:
    return SqliteProxyStore(settings.database_url, settings=settings)


def _countries_from_args(args: argparse.Namespace, settings: Settings) -> list[str]:
    raw = getattr(args, "country", None) or getattr(args, "countries", None)
    countries = parse_countries(raw)
    if countries:
        return countries
    return parse_countries(settings.countries) or [settings.country or "BR"]


def _apply_common_args(settings: Settings, args: argparse.Namespace) -> Settings:
    if getattr(args, "max_pages", None) is not None:
        settings = replace(settings, max_pages=args.max_pages)
    if getattr(args, "page_size", None) is not None:
        settings = replace(settings, page_size=args.page_size)
    if getattr(args, "probe_url", None):
        settings = replace(settings, probe_url=args.probe_url)
    if getattr(args, "expect_country", None) is not None:
        settings = replace(settings, expect_country=args.expect_country.upper())
    if getattr(args, "concurrency", None):
        settings = replace(settings, validate_concurrency=args.concurrency)
    countries = parse_countries(
        getattr(args, "country", None) or getattr(args, "countries", None)
    )
    if countries:
        settings = replace(settings, countries=",".join(countries))
    return settings


async def cmd_scrape(settings: Settings, args: argparse.Namespace) -> int:
    settings = _apply_common_args(settings, args)
    countries = _countries_from_args(args, settings)
    store = _store(settings)

    total_scraped = total_inserted = total_refreshed = total_touched = 0
    for country in countries:
        country_settings = apply_country(settings, country)
        # keep shared scrape knobs
        country_settings = replace(
            country_settings,
            max_pages=settings.max_pages,
            page_size=settings.page_size,
            scrape_timeout_seconds=settings.scrape_timeout_seconds,
            page_delay_seconds=settings.page_delay_seconds,
            emulation=settings.emulation,
            database_url=settings.database_url,
        )
        print(
            f"scraping country={country} url={country_settings.scrape_url} "
            f"(max_pages={country_settings.max_pages}, "
            f"page_size={country_settings.page_size})"
        )
        proxies = await scrape_freeproxy_world(country_settings)
        inserted, refreshed, touched = store.upsert_scraped(proxies)
        print(
            f"  country={country} scraped={len(proxies)} inserted={inserted} "
            f"refreshed_fresh={refreshed} touched={touched}"
        )
        total_scraped += len(proxies)
        total_inserted += inserted
        total_refreshed += refreshed
        total_touched += touched

    print(
        f"done countries={countries} scraped={total_scraped} "
        f"inserted={total_inserted} refreshed_fresh={total_refreshed} "
        f"touched={total_touched} db={settings.database_url}"
    )
    print("stats=", store.stats())
    return 0


async def cmd_validate(settings: Settings, args: argparse.Namespace) -> int:
    settings = _apply_common_args(settings, args)
    countries = parse_countries(
        getattr(args, "country", None) or getattr(args, "countries", None)
    )

    store = _store(settings)
    proxies = store.list(
        status=None if args.status == "all" else args.status,
        countries=countries or None,
        limit=args.limit,
    )
    if not proxies:
        print("no proxies matched", file=sys.stderr)
        return 1

    print(
        f"validating {len(proxies)} via per-proxy probes "
        f"(concurrency={settings.validate_concurrency}, status={args.status}, "
        f"countries={countries or 'ALL'})"
    )

    def on_progress(done: int, total: int, proxy) -> None:
        step = max(1, total // 10)
        if done == total or done % step == 0:
            print(
                f"  progress {done}/{total} "
                f"last={proxy.host}:{proxy.port} status={proxy.status} "
                f"score={proxy.score}",
                flush=True,
            )

    started = asyncio.get_running_loop().time()
    checked = await validate_many(
        proxies,
        store=store,
        settings=settings,
        on_progress=on_progress,
        use_settings_probe=bool(getattr(args, "use_settings_probe", False)),
    )
    elapsed = asyncio.get_running_loop().time() - started
    alive = sum(1 for p in checked if p.status == "alive")
    degraded = sum(1 for p in checked if p.status == "degraded")
    dead = sum(1 for p in checked if p.status in ("dead", "retired"))
    rate = (len(checked) / elapsed) if elapsed else 0.0
    print(
        f"checked={len(checked)} alive={alive} degraded={degraded} "
        f"dead/retired={dead} elapsed={elapsed:.1f}s rate={rate:.1f}/s"
    )
    print("stats=", store.stats())
    top = [p for p in checked if p.score is not None]
    top.sort(key=lambda p: p.score or 0, reverse=True)
    if top:
        print("top_sample=")
        print(
            json.dumps(
                [
                    {
                        "key": p.key,
                        "country": p.country,
                        "status": p.status,
                        "score": p.score,
                        "uptime": p.uptime,
                        "latency_ms": p.last_latency_ms,
                        "egress_ip": p.egress_ip,
                    }
                    for p in top[:5]
                ],
                indent=2,
            )
        )
    return 0


async def cmd_run(settings: Settings, args: argparse.Namespace) -> int:
    settings = _apply_common_args(settings, args)
    countries = _countries_from_args(args, settings)
    code = await cmd_scrape(settings, args)
    if code != 0:
        return code
    validate_ns = argparse.Namespace(
        limit=args.limit,
        concurrency=args.concurrency,
        probe_url=None,
        expect_country=None,
        country=",".join(countries),
        countries=None,
        status="pending",
        use_settings_probe=False,
        max_pages=None,
        page_size=None,
    )
    return await cmd_validate(settings, validate_ns)


def cmd_stats(settings: Settings, args: argparse.Namespace) -> int:
    store = _store(settings)
    print("stats=", store.stats())
    top = store.list(order_by_score=True, limit=args.top)
    if not top:
        return 0
    print("top=")
    print(
        json.dumps(
            [
                {
                    "key": p.key,
                    "country": p.country,
                    "status": p.status,
                    "score": p.score,
                    "uptime": p.uptime,
                    "avg_latency_ms": p.avg_latency_ms,
                    "check_count": p.check_count,
                }
                for p in top
            ],
            indent=2,
        )
    )
    return 0


async def cmd_worker(settings: Settings, args: argparse.Namespace) -> int:
    settings = _apply_common_args(settings, args)
    countries = _countries_from_args(args, settings)
    settings = replace(settings, countries=",".join(countries))
    worker = ProxyWorker(settings)
    await worker.run(run_scrape_first=not args.no_initial_scrape)
    return 0


def cmd_init_db(settings: Settings) -> int:
    init_db(settings.database_url)
    print(f"initialized {settings.database_url}")
    return 0


def cmd_import_json(settings: Settings, args: argparse.Namespace) -> int:
    store = _store(settings)
    records = ProxyFileStore(args.path).load()
    n = store.import_records(records)
    print(f"imported touched={n} from {args.path}")
    print("stats=", store.stats())
    return 0


def cmd_export_json(settings: Settings, args: argparse.Namespace) -> int:
    store = _store(settings)
    records = store.list(status=None if args.status == "all" else args.status)
    ProxyFileStore(args.out).save(records)
    print(f"exported {len(records)} -> {args.out}")
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = Settings.from_env()

    if args.command == "scrape":
        raise SystemExit(asyncio.run(cmd_scrape(settings, args)))
    if args.command == "validate":
        raise SystemExit(asyncio.run(cmd_validate(settings, args)))
    if args.command == "run":
        raise SystemExit(asyncio.run(cmd_run(settings, args)))
    if args.command == "stats":
        raise SystemExit(cmd_stats(settings, args))
    if args.command == "worker":
        raise SystemExit(asyncio.run(cmd_worker(settings, args)))
    if args.command == "init-db":
        raise SystemExit(cmd_init_db(settings))
    if args.command == "import-json":
        raise SystemExit(cmd_import_json(settings, args))
    if args.command == "export-json":
        raise SystemExit(cmd_export_json(settings, args))
    parser.error(f"unknown command {args.command}")


if __name__ == "__main__":
    main()

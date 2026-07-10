from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import replace

from scaffold_proxy.collectors.freeproxy_world import scrape_freeproxy_world
from scaffold_proxy.config import Settings, apply_country
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
        help="ISO country code for freeproxy.world (default: BR). "
        "Non-BR defaults probe to ipify with no country check.",
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
    validate.add_argument("--country", type=str, default=None)
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
        "--countries",
        type=str,
        default=None,
        help="Comma-separated countries (overrides COUNTRIES)",
    )

    initdb = sub.add_parser("init-db", help="Create SQLite tables")

    import_json = sub.add_parser("import-json", help="Import a legacy JSON proxy file")
    import_json.add_argument("path", type=str)

    export_json = sub.add_parser("export-json", help="Export DB pool to JSON")
    export_json.add_argument("--out", type=str, default="data/proxies_export.json")
    export_json.add_argument("--status", type=str, default="all")

    return parser


def _store(settings: Settings) -> SqliteProxyStore:
    return SqliteProxyStore(settings.database_url, settings=settings)


def _apply_scrape_args(settings: Settings, args: argparse.Namespace) -> Settings:
    if getattr(args, "country", None):
        settings = apply_country(settings, args.country)
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
    if getattr(args, "countries", None):
        settings = replace(settings, countries=args.countries)
    return settings


async def cmd_scrape(settings: Settings, args: argparse.Namespace) -> int:
    settings = _apply_scrape_args(settings, args)
    store = _store(settings)
    print(
        f"scraping country={settings.country} url={settings.scrape_url} "
        f"(max_pages={settings.max_pages}, page_size={settings.page_size})"
    )
    proxies = await scrape_freeproxy_world(settings)
    inserted, refreshed, touched = store.upsert_scraped(proxies)
    print(
        f"scraped={len(proxies)} inserted={inserted} refreshed_fresh={refreshed} "
        f"touched={touched} db={settings.database_url}"
    )
    print("stats=", store.stats())
    return 0


async def cmd_validate(settings: Settings, args: argparse.Namespace) -> int:
    if args.concurrency:
        settings = replace(settings, validate_concurrency=args.concurrency)
    if getattr(args, "probe_url", None):
        settings = replace(settings, probe_url=args.probe_url)
    if getattr(args, "expect_country", None) is not None:
        settings = replace(settings, expect_country=args.expect_country.upper())

    store = _store(settings)
    proxies = store.list(
        status=None if args.status == "all" else args.status,
        country=args.country,
        limit=args.limit,
    )
    if not proxies:
        print("no proxies matched", file=sys.stderr)
        return 1

    print(
        f"validating {len(proxies)} via per-proxy probes "
        f"(concurrency={settings.validate_concurrency}, status={args.status})"
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
    settings = _apply_scrape_args(settings, args)
    code = await cmd_scrape(settings, args)
    if code != 0:
        return code
    validate_ns = argparse.Namespace(
        limit=args.limit,
        concurrency=args.concurrency,
        probe_url=None,
        expect_country=None,
        country=settings.country,
        status="pending",
        use_settings_probe=False,
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
    settings = _apply_scrape_args(settings, args)
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

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import replace

from scaffold_proxy.collectors.freeproxy_world import scrape_freeproxy_world
from scaffold_proxy.config import Settings
from scaffold_proxy.store import ProxyFileStore
from scaffold_proxy.validator import validate_many


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scaffold-proxy",
        description="Collect and validate free BR proxies",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scrape = sub.add_parser("scrape", help="Scrape freeproxy.world BR list into a JSON file")
    scrape.add_argument("--max-pages", type=int, default=None)
    scrape.add_argument("--out", type=str, default=None, help="Output JSON path")

    validate = sub.add_parser(
        "validate",
        help="Validate proxies from JSON via BR IP-check endpoint",
    )
    validate.add_argument("--file", type=str, default=None, help="Proxies JSON path")
    validate.add_argument("--limit", type=int, default=None, help="Only check first N")
    validate.add_argument("--concurrency", type=int, default=None)
    validate.add_argument(
        "--status",
        choices=["pending", "alive", "dead", "all"],
        default="pending",
        help="Which stored statuses to validate (default: pending)",
    )

    run = sub.add_parser("run", help="Scrape then validate in one shot")
    run.add_argument("--max-pages", type=int, default=None)
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--concurrency", type=int, default=None)
    run.add_argument("--out", type=str, default=None)

    return parser


async def cmd_scrape(settings: Settings, args: argparse.Namespace) -> int:
    if args.max_pages is not None:
        settings = replace(settings, max_pages=args.max_pages)
    if args.out:
        settings = replace(settings, proxies_file=args.out)

    print(f"scraping {settings.scrape_url} (emulation={settings.emulation})")
    proxies = await scrape_freeproxy_world(settings)
    store = ProxyFileStore(settings.proxies_file)
    merged = store.upsert(proxies)
    print(f"scraped={len(proxies)} stored={len(merged)} file={settings.proxies_file}")
    return 0


async def cmd_validate(settings: Settings, args: argparse.Namespace) -> int:
    if args.file:
        settings = replace(settings, proxies_file=args.file)
    if args.concurrency:
        settings = replace(settings, validate_concurrency=args.concurrency)

    store = ProxyFileStore(settings.proxies_file)
    proxies = store.load()
    if not proxies:
        print(f"no proxies in {settings.proxies_file}", file=sys.stderr)
        return 1

    if args.status != "all":
        proxies = [p for p in proxies if p.status == args.status]
    if args.limit is not None:
        proxies = proxies[: args.limit]

    print(
        f"validating {len(proxies)} proxies via {settings.probe_url} "
        f"(expect_country={settings.expect_country}, "
        f"concurrency={settings.validate_concurrency})"
    )

    def on_progress(done: int, total: int, proxy) -> None:
        # Print every 10% or on completion so large batches stay observable.
        step = max(1, total // 10)
        if done == total or done % step == 0:
            print(
                f"  progress {done}/{total} "
                f"last={proxy.host}:{proxy.port} status={proxy.status}",
                flush=True,
            )

    started = asyncio.get_running_loop().time()
    checked = await validate_many(proxies, settings=settings, on_progress=on_progress)
    elapsed = asyncio.get_running_loop().time() - started

    # merge back into full store
    by_key = {p.key: p for p in store.load()}
    for proxy in checked:
        by_key[proxy.key] = proxy
    merged = sorted(by_key.values(), key=lambda p: (p.host, p.port))
    store.save(merged)

    alive = sum(1 for p in checked if p.status == "alive")
    dead = sum(1 for p in checked if p.status == "dead")
    rate = (len(checked) / elapsed) if elapsed else 0.0
    print(
        f"checked={len(checked)} alive={alive} dead={dead} "
        f"elapsed={elapsed:.1f}s rate={rate:.1f}/s file={settings.proxies_file}"
    )
    if alive:
        samples = [p.to_dict() for p in checked if p.status == "alive"][:5]
        print("alive_sample=")
        print(json.dumps(samples, indent=2))
    return 0


async def cmd_run(settings: Settings, args: argparse.Namespace) -> int:
    scrape_ns = argparse.Namespace(max_pages=args.max_pages, out=args.out)
    code = await cmd_scrape(settings, scrape_ns)
    if code != 0:
        return code
    settings = Settings.from_env()
    if args.out:
        settings = replace(settings, proxies_file=args.out)
    validate_ns = argparse.Namespace(
        file=settings.proxies_file,
        limit=args.limit,
        concurrency=args.concurrency,
        status="pending",
    )
    return await cmd_validate(settings, validate_ns)


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
    parser.error(f"unknown command {args.command}")


if __name__ == "__main__":
    main()

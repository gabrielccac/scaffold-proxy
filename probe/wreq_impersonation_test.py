"""Probe freeproxy.world with multiple wreq emulations."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from wreq import Client, Emulation

URL = "https://www.freeproxy.world/?type=&anonymity=&country=BR&speed=&port="
URL2 = URL + "&page=2"
OUT = Path(__file__).resolve().parent / "wreq_out"

CANDIDATES = [
    "Chrome120",
    "Chrome124",
    "Chrome131",
    "Chrome136",
    "Chrome147",
    "Firefox128",
    "Firefox135",
    "Firefox147",
    "Safari18",
    "Safari18_5",
    "Safari17_5",
    "Edge131",
    "Edge147",
    "Opera119",
    "Opera130",
]


def extract_proxies(html: str) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []
    for m in re.finditer(
        r"<tr>\s*<td[^>]*>\s*(\d+\.\d+\.\d+\.\d+)\s*</td>\s*<td>\s*<a[^>]*>\s*(\d+)\s*</a>",
        html,
        re.S | re.I,
    ):
        rows.append((m.group(1), int(m.group(2))))
    return rows


def is_challenge(html: str, status: int) -> bool:
    if status in (403, 503, 429) and not extract_proxies(html):
        return True
    return "just a moment" in html.lower()


async def try_one(name: str) -> dict:
    result: dict = {"emulation": name}
    client = Client(emulation=getattr(Emulation, name), cookie_store=True)
    try:
        r1 = await client.get(URL)
        status1 = r1.status.as_int()
        text1 = await r1.text()
        proxies1 = extract_proxies(text1)
        title = re.search(r"<title>(.*?)</title>", text1, re.I | re.S)
        cf = re.search(r"__CF\$cv\$params=\{[^}]*\}", text1)
        result.update(
            {
                "p1_status": status1,
                "p1_len": len(text1),
                "p1_challenge": is_challenge(text1, status1),
                "p1_proxies": len(proxies1),
                "p1_sample": proxies1[:3],
                "p1_title": title.group(1).strip() if title else "",
                "p1_cf_params": cf.group(0) if cf else None,
            }
        )
        (OUT / f"{name}_p1.html").write_text(text1, encoding="utf-8", errors="replace")

        r2 = await client.get(URL2)
        status2 = r2.status.as_int()
        text2 = await r2.text()
        proxies2 = extract_proxies(text2)
        title2 = re.search(r"<title>(.*?)</title>", text2, re.I | re.S)
        result.update(
            {
                "p2_status": status2,
                "p2_len": len(text2),
                "p2_challenge": is_challenge(text2, status2),
                "p2_proxies": len(proxies2),
                "p2_sample": proxies2[:3],
                "p2_title": title2.group(1).strip() if title2 else "",
            }
        )
        (OUT / f"{name}_p2.html").write_text(text2, encoding="utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001 - probe script
        result["error"] = repr(e)
    finally:
        close = client.close()
        if asyncio.iscoroutine(close):
            await close
    return result


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    for name in CANDIDATES:
        if not hasattr(Emulation, name):
            continue
        print(f"=== {name} ===", flush=True)
        r = await try_one(name)
        print(
            f"  p1={r.get('p1_status')} proxies={r.get('p1_proxies')} "
            f"ch={r.get('p1_challenge')} | p2={r.get('p2_status')} "
            f"proxies={r.get('p2_proxies')} ch={r.get('p2_challenge')} "
            f"err={r.get('error')}"
        )
        results.append(r)
        await asyncio.sleep(2)
    (OUT / "impersonation_results.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    asyncio.run(main())

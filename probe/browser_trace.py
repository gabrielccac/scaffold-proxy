import asyncio
import json
import re
from pathlib import Path
from playwright.async_api import async_playwright

URL = "https://www.freeproxy.world/?type=&anonymity=&country=BR&speed=&port="
OUT = Path("/workspace/probe/browser_out")
OUT.mkdir(parents=True, exist_ok=True)

async def main():
    events = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            locale="en-US",
        )
        page = await context.new_page()

        async def on_request(req):
            events.append({
                "kind": "request",
                "url": req.url,
                "method": req.method,
                "resource_type": req.resource_type,
                "headers": await req.all_headers(),
                "post_data": req.post_data,
            })

        async def on_response(resp):
            req = resp.request
            body_preview = None
            body_text = None
            try:
                ct = resp.headers.get("content-type", "")
                if any(x in ct for x in ("json", "text", "html", "javascript", "xml")) or req.resource_type in ("xhr", "fetch", "document"):
                    body_text = await resp.text()
                    body_preview = body_text[:4000]
            except Exception as e:
                body_preview = f"<err reading body: {e}>"
            events.append({
                "kind": "response",
                "url": resp.url,
                "status": resp.status,
                "method": req.method,
                "resource_type": req.resource_type,
                "headers": resp.headers,
                "body_preview": body_preview,
                "body_len": len(body_text) if body_text is not None else None,
            })
            # save interesting bodies
            if req.resource_type in ("xhr", "fetch") or "proxy" in resp.url.lower() or "api" in resp.url.lower():
                safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", resp.url)[:180]
                (OUT / f"resp_{safe}.txt").write_text(body_text or "", encoding="utf-8", errors="replace")

        page.on("request", on_request)
        page.on("response", on_response)

        print("Navigating page 1...")
        await page.goto(URL, wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(3000)
        html1 = await page.content()
        (OUT / "page1.html").write_text(html1, encoding="utf-8")
        print(f"Page1 title: {await page.title()} len={len(html1)}")

        # try click page 2 if present
        clicked = False
        for sel in [
            'a[href*="page=2"]',
            'a:has-text("2")',
            '.pagination a:has-text("2")',
            'li.page-item a:has-text("2")',
            'a[rel="next"]',
        ]:
            loc = page.locator(sel).first
            try:
                if await loc.count() > 0 and await loc.is_visible():
                    print(f"Clicking pagination via {sel}")
                    await loc.click()
                    clicked = True
                    break
            except Exception as e:
                print(f"sel {sel} failed: {e}")

        if not clicked:
            # try direct navigation to page 2 variants
            for u in [
                URL + "&page=2",
                "https://www.freeproxy.world/?page=2&type=&anonymity=&country=BR&speed=&port=",
                "https://www.freeproxy.world/page/2?type=&anonymity=&country=BR&speed=&port=",
            ]:
                print(f"Trying navigate {u}")
                await page.goto(u, wait_until="networkidle", timeout=60000)
                await page.wait_for_timeout(2000)
                break
        else:
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(3000)

        html2 = await page.content()
        (OUT / "page2.html").write_text(html2, encoding="utf-8")
        print(f"Page2 url={page.url} len={len(html2)}")

        # dump cookies
        cookies = await context.cookies()
        (OUT / "cookies.json").write_text(json.dumps(cookies, indent=2), encoding="utf-8")

        # summarize xhr/fetch
        interesting = [e for e in events if e.get("resource_type") in ("xhr", "fetch") or e["kind"] == "response" and e.get("resource_type") in ("xhr", "fetch")]
        summary = []
        for e in events:
            if e["kind"] == "response" and e.get("resource_type") in ("xhr", "fetch", "document"):
                summary.append({
                    "status": e["status"],
                    "method": e["method"],
                    "type": e["resource_type"],
                    "url": e["url"],
                    "body_len": e.get("body_len"),
                    "body_preview": (e.get("body_preview") or "")[:500],
                })
        (OUT / "network_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        (OUT / "all_events.json").write_text(json.dumps(events, indent=2, default=str), encoding="utf-8")

        print("=== XHR/FETCH/DOCUMENT responses ===")
        for s in summary:
            print(f"{s['status']} {s['method']} [{s['type']}] {s['url']} body_len={s['body_len']}")
            if s["type"] in ("xhr", "fetch"):
                print("  preview:", repr(s["body_preview"][:300]))

        await browser.close()

asyncio.run(main())

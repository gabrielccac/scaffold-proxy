# freeproxy.world probe findings

Source under test:

`https://www.freeproxy.world/?type=&anonymity=&country=BR&speed=&port=`

## Verdict

There is **no site-owned XHR/fetch that returns proxies**. The list is **server-rendered HTML** (`table.table`, 50 rows/page). Pagination is a normal document GET with `&page=N`.

The XHR traffic you see (especially on page 2+) is **Cloudflare challenge**, not a proxy API.

## Network model

### Page 1 (cold)

| Step | What happens |
|------|----------------|
| `GET /?…&country=BR` | `200` HTML with full proxy table |
| Inline CF snippet | injects `window.__CF$cv$params={r:'…',t:'…'}` |
| `GET /cdn-cgi/challenge-platform/.../jsd/main.js` | CF JS |
| `POST .../jsd/oneshot/...` | CF “managed challenge” beacon (empty body) |

### Page 2+ (when fingerprint is weak / headless)

| Step | What happens |
|------|----------------|
| `GET /?…&page=2` | often `307` → `403` “Just a moment…” |
| `GET .../orchestrate/chl_page/v1?ray=…` | CF challenge orchestrator |
| `POST .../fo/…` | CF challenge solve payload (~100KB opaque body) |
| On success | browser would reload with `cf_clearance` and get HTML table |

### Page 2+ (with good wreq impersonation)

Same URL returns **`200` HTML table directly** — no need to parse/solve CF if TLS fingerprint passes.

## The “element from the first HTML”

Found in page HTML (Cloudflare, not app CSRF):

```js
window.__CF$cv$params={r:'a19172733f7af8cb',t:'MTc4MzcwNjIwNw=='};
```

- `r` — CF ray / request id  
- `t` — base64 timestamp (`MTc4MzcwNjIwNw==` → unix-ish stamp)  
- Consumed by `/cdn-cgi/challenge-platform/scripts/jsd/main.js` for subsequent CF posts  

There is **no Laravel/XSRF/hidden form token** for the proxy list. Cookies observed after a real browser pass: `cf_clearance` (+ analytics). Successful **wreq** scrapes did not need us to manually plumb `__CF$cv$params`; fingerprint alone was enough for pages 1–3.

## Proxy extraction shape

Each row in `table.table tbody tr`:

| Field | Where |
|-------|--------|
| host | first `<td>` text (`x.x.x.x`) |
| port | `<a href="/?port=PORT">` |
| country | `/?country=BR` cell (fixed for this URL) |
| city | `span.text-truncate[title]` |
| speed_ms | `NNN ms` |
| protocol | badge text: `http` / `https` / `socks4` / `socks5` |
| anonymity | `/?anonymity=…` link text (`No` / `High`) |

Pagination links: `?type=&anonymity=&country=BR&speed=&port=&page=N` (seen up to page 6 for BR at probe time). Pages are disjoint (0 overlap p1∩p2∩p3 in sample).

## wreq impersonation results

Client: `wreq.Client(emulation=…, cookie_store=True)` against page 1 then page 2.

| Emulation | Page 1 | Page 2 |
|-----------|--------|--------|
| Chrome120 | 200 / 50 proxies | 200 / 50 |
| Chrome124 | 403 challenge | 403 |
| Chrome131 | 403 challenge | 403 |
| Chrome136 | 200 / 50 | 200 / 50 |
| Chrome147 | 200 / 50 | 200 / 50 |
| Firefox128 | 200 / 50 | 200 / 50 |
| Firefox135 | 200 / 50 | 200 / 50 |
| Firefox147 | 200 / 50 | 200 / 50 |
| Safari17_5 | 200 / 50 | 200 / 50 |
| Safari18 | 200 / 50 | 200 / 50 |
| Safari18_5 | 200 / 50 | 200 / 50 |
| Edge131 | 403 challenge | 403 |
| Edge147 | 200 / 50 | 200 / 50 |
| Opera119 | 403 challenge | 403 |
| Opera130 | 403 challenge | 403 |

**Recommended defaults:** `Chrome147` or `Firefox147` (also `Chrome136`, `Safari18_5`, `Edge147`). Avoid mid Chrome/Edge/Opera profiles that failed in this run (`Chrome124/131`, `Edge131`, `Opera*`).

Note: results can drift as Cloudflare updates; keep a small allowlist + fallback rotation.

## Playwright note

Headless Chromium often gets page 1, then **fails CF on page 2** (`Just a moment…`, stuck on `.../fo/...` XHR). That XHR is CF, not proxies. For this source, **prefer wreq HTML scrape** over browser automation.

## Collector implications (P0)

1. `GET` filter URL with wreq (`Chrome147`).  
2. Parse `table.table` rows → normalize.  
3. Paginate `&page=2..N` on the **same client** (cookie jar).  
4. Stop when a page returns 0 rows or challenge/non-200.  
5. No separate “proxy API” client needed for freeproxy.world.

Artifacts: `probe/wreq_out/impersonation_results.json`, `probe/wreq_out/parsed_sample.json`, browser traces under `probe/browser_out/`.

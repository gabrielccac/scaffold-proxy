# scaffold-proxy

Collect free proxies from freeproxy.world, store them in a local JSON file, and validate them through an IP-check endpoint.

## Setup

```bash
python3 -m pip install -e .
```

## Usage

```bash
# BR (default): meuip probe + expect country=BR
python3 -m scaffold_proxy scrape --max-pages 6
python3 -m scaffold_proxy validate --concurrency 100

# Other country: auto-switches probe to ipify (no country check)
python3 -m scaffold_proxy run --country US --max-pages 3 --concurrency 100

# Explicit overrides
python3 -m scaffold_proxy run --country DE \
  --probe-url https://ipwho.is/ --expect-country DE
```

Pagination stops when a page is **empty**, has **no new rows**, or is a **short page** (`rows < page_size`, default 50). `--max-pages` remains a safety cap.

## Config

| Flag / env | Default |
|------------|---------|
| `--country` / `COUNTRY` | `BR` |
| `--max-pages` / `MAX_PAGES` | `6` |
| `--page-size` / `PAGE_SIZE` | `50` |
| `--probe-url` / `PROBE_URL` | BR→meuip, else→ipify |
| `--expect-country` / `EXPECT_COUNTRY` | BR→`BR`, else→empty |
| `--concurrency` / `VALIDATE_CONCURRENCY` | `100` |
| `PROXIES_FILE` | `data/proxies.json` |

Alive = probe HTTP 200 with a parseable egress IP, and (if set) matching `expect_country`.

# scaffold-proxy

Collect free proxies from freeproxy.world, persist them in **SQLite**, score them from recent checks, and re-validate on an in-process schedule.

## Setup

```bash
python3 -m pip install -e .
python3 -m scaffold_proxy init-db
```

## Usage

```bash
# scrape + validate pending (per-proxy probes: BR→meuip, else→ipify)
python3 -m scaffold_proxy run --country US --max-pages 5

# validate by status
python3 -m scaffold_proxy validate --status pending --limit 100
python3 -m scaffold_proxy stats

# background worker (scrape + routine rechecks)
COUNTRIES=BR,US,CA python3 -m scaffold_proxy worker

# migrate old JSON dumps
python3 -m scaffold_proxy import-json data/proxies_us.json
```

## Status & scoring

Statuses: `pending → alive|degraded|dead → retired`  
Re-seen dead/retired in scrape → reset to **pending** (history kept).  
Score 0–100 from last `SCORE_WINDOW` checks (uptime, latency, freshness, streak).

## Config (env)

| Variable | Default |
|----------|---------|
| `DATABASE_URL` | `sqlite:///./data/proxies.db` |
| `COUNTRIES` | `BR` |
| `SCORE_WINDOW` | `20` |
| `VALIDATE_CONCURRENCY` | `100` |
| `SCRAPE_INTERVAL_SECONDS` | `900` |
| `VALIDATE_PENDING_INTERVAL_SECONDS` | `60` |
| `VALIDATE_ALIVE_INTERVAL_SECONDS` | `600` |
| `VALIDATE_DEAD_INTERVAL_SECONDS` | `1800` |

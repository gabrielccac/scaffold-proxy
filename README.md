# scaffold-proxy

Collect free BR proxies from freeproxy.world, store them in a local JSON file, and validate them through a Brazilian IP-check endpoint.

## Setup

```bash
python3 -m pip install -e .
# or: pip install wreq && PYTHONPATH=src ...
```

## Usage

```bash
# scrape BR list → data/proxies.json
python3 -m scaffold_proxy scrape --max-pages 3

# validate pending proxies via https://meuip.martins.eng.br/all.json
python3 -m scaffold_proxy validate --limit 50

# scrape + validate
python3 -m scaffold_proxy run --max-pages 2 --limit 40
```

## Config (env)

| Variable | Default |
|----------|---------|
| `WREQ_EMULATION` | `Chrome147` |
| `PROXIES_FILE` | `data/proxies.json` |
| `PROBE_URL` | `https://meuip.martins.eng.br/all.json` |
| `EXPECT_COUNTRY` | `BR` |
| `VALIDATE_CONCURRENCY` | `100` |
| `VALIDATE_TIMEOUT_SECONDS` | `8` |
| `MAX_PAGES` | `6` |

Validation fans out with `asyncio` + a semaphore (`VALIDATE_CONCURRENCY`). One shared `wreq` client is reused; each check sets `proxy=` per request so dead proxies fail independently without serializing the batch.

A proxy is **alive** when the probe returns HTTP 200 JSON with an egress IP and `country == BR`.

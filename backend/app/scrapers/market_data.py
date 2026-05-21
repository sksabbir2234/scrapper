import time
from datetime import datetime, timezone

import httpx

SYMBOLS = {
    "SPY": "S&P 500 ETF",
    "QQQ": "Nasdaq 100 ETF",
    "BTC-USD": "Bitcoin",
    "GLD": "Gold ETF",
    "DXY": "US Dollar Index",
}

_cache: dict = {}
_cache_ts: float = 0
CACHE_TTL = 300  # 5 minutes


def fetch_market_snapshot(ttl: int = CACHE_TTL) -> list[dict]:
    global _cache, _cache_ts
    now = time.time()
    if _cache and (now - _cache_ts) < ttl:
        return _cache.get("data", [])

    results = []
    for symbol, label in SYMBOLS.items():
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
            params = {"interval": "1d", "range": "5d"}
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = httpx.get(url, params=params, headers=headers, timeout=15)
            if resp.status_code != 200:
                results.append({"symbol": symbol, "label": label, "error": True})
                continue

            data = resp.json()
            chart = data.get("chart", {}).get("result", [])
            if not chart:
                results.append({"symbol": symbol, "label": label, "error": True})
                continue

            meta = chart[0].get("meta", {})
            closes = chart[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
            closes = [c for c in closes if c is not None]

            price = meta.get("regularMarketPrice", closes[-1] if closes else 0)
            prev_close = meta.get("chartPreviousClose", closes[-2] if len(closes) > 1 else price)
            change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0

            results.append({
                "symbol": symbol,
                "label": label,
                "price": round(price, 2),
                "change_pct": round(change_pct, 2),
                "sparkline": [round(c, 2) for c in closes[-7:]],
                "error": False,
            })
        except Exception:
            results.append({"symbol": symbol, "label": label, "error": True})

    _cache = {"data": results}
    _cache_ts = now
    return results

#!/usr/bin/env python3
"""串串商機雷達：搜尋公開網頁結果並輸出 CSV / Excel。"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import pandas as pd
from dateutil import parser as date_parser
from playwright.async_api import async_playwright

ROOT = Path(__file__).parent
OUT = ROOT / "output"
TZ_TAIPEI = timezone(timedelta(hours=8))

RELATIVE_PATTERNS = [
    (re.compile(r"(\d+)\s*(?:分鐘|分|minutes?|mins?)\s*(?:前|ago)?", re.I), "minutes"),
    (re.compile(r"(\d+)\s*(?:小時|hours?|hrs?)\s*(?:前|ago)?", re.I), "hours"),
]


def extract_time(text: str, now: datetime):
    text = text or ""
    for pattern, unit in RELATIVE_PATTERNS:
        match = pattern.search(text)
        if match:
            value = int(match.group(1))
            return now - timedelta(**{unit: value}), f"relative_{unit}"
    try:
        candidate = re.search(
            r"(20\d{2}[年/\-.]\d{1,2}[月/\-.]\d{1,2}(?:日)?(?:\s+\d{1,2}:\d{2})?)",
            text,
        )
        if candidate:
            normalized = candidate.group(1).replace("年", "-").replace("月", "-").replace("日", "")
            return date_parser.parse(normalized).replace(tzinfo=TZ_TAIPEI), "absolute"
    except (ValueError, TypeError):
        pass
    return None, "unknown"


def clean_url(url: str) -> str:
    if not url:
        return ""
    return url.split("#")[0]


async def search_bing(page, query: str, limit: int):
    await page.goto(
        f"https://www.bing.com/search?q={quote_plus(query)}&setlang=zh-hant",
        wait_until="domcontentloaded",
        timeout=60000,
    )
    await page.wait_for_timeout(1500)
    results = []
    for item in await page.locator("li.b_algo").all():
        link = item.locator("h2 a")
        if await link.count() == 0:
            continue
        title = (await link.first.inner_text()).strip()
        url = clean_url(await link.first.get_attribute("href") or "")
        snippet_node = item.locator(".b_caption p")
        snippet = (await snippet_node.first.inner_text()).strip() if await snippet_node.count() else ""
        if url and title:
            results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= limit:
            break
    return results


async def main():
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    now = datetime.now(TZ_TAIPEI)
    max_age = int(config.get("max_age_minutes", 60))
    strict = bool(config.get("strict_recent_only", True))
    rows = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            locale="zh-TW",
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        )
        page = await context.new_page()
        for keyword in config["keywords"]:
            for platform in config["platforms"]:
                query = f'"{keyword}" site:{platform}'
                try:
                    found = await search_bing(page, query, int(config.get("max_results_per_keyword", 20)))
                except Exception as exc:
                    print(f"[WARN] {query}: {exc}")
                    continue
                for result in found:
                    host = urlparse(result["url"]).netloc.lower()
                    if platform not in host:
                        continue
                    published, evidence = extract_time(
                        f'{result["title"]} {result["snippet"]}', now
                    )
                    age_minutes = (
                        round((now - published).total_seconds() / 60, 1)
                        if published else None
                    )
                    verified_recent = age_minutes is not None and 0 <= age_minutes <= max_age
                    if strict and not verified_recent:
                        continue
                    rows.append({
                        "關鍵字": keyword,
                        "平台": platform,
                        "標題": result["title"],
                        "摘要": result["snippet"],
                        "原始連結": result["url"],
                        "發布時間": published.isoformat() if published else "",
                        "距今分鐘": age_minutes if age_minutes is not None else "",
                        "時間判定": evidence,
                        "符合60分鐘": "是" if verified_recent else "未確認",
                        "蒐集時間": now.isoformat(),
                    })
                await page.wait_for_timeout(800)
        await browser.close()

    columns = ["關鍵字","平台","標題","摘要","原始連結","發布時間","距今分鐘","時間判定","符合60分鐘","蒐集時間"]
    frame = pd.DataFrame(rows, columns=columns).drop_duplicates(subset=["原始連結"])
    OUT.mkdir(exist_ok=True)
    frame.to_csv(OUT / "latest.csv", index=False, encoding="utf-8-sig")
    frame.to_excel(OUT / "latest.xlsx", index=False)
    summary = {
        "collected_at": now.isoformat(),
        "strict_recent_only": strict,
        "max_age_minutes": max_age,
        "result_count": len(frame),
        "note": "只使用公開搜尋結果；無法確認發布時間的內容在嚴格模式下不收錄。"
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""串串商機雷達：搜尋公開網頁，分開輸出近期確認與候選商機。"""
from __future__ import annotations

import asyncio
import base64
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import pandas as pd
from dateutil import parser as date_parser
from playwright.async_api import async_playwright

ROOT = Path(__file__).parent
OUT = ROOT / "output"
TZ_TAIPEI = timezone(timedelta(hours=8))
COLUMNS = ["關鍵字","平台","標題","摘要","原始連結","發布時間","距今分鐘","時間判定","分類","蒐集時間"]

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
            parsed = date_parser.parse(normalized)
            return parsed.replace(tzinfo=TZ_TAIPEI), "absolute"
    except (ValueError, TypeError):
        pass
    return None, "unknown"


def clean_url(url: str) -> str:
    """盡量還原 Bing 包裝過的真正社群連結。"""
    if not url:
        return ""
    parsed = urlparse(url)
    if "bing.com" in parsed.netloc:
        encoded = parse_qs(parsed.query).get("u", [""])[0]
        if encoded.startswith("a1"):
            try:
                payload = encoded[2:] + "=" * (-len(encoded[2:]) % 4)
                decoded = base64.urlsafe_b64decode(payload).decode("utf-8")
                if decoded.startswith("http"):
                    url = decoded
            except Exception:
                pass
        elif encoded.startswith("http"):
            url = unquote(encoded)
    return url.split("#")[0]


async def search_bing(page, query: str, limit: int):
    await page.goto(
        f"https://www.bing.com/search?q={quote_plus(query)}&setlang=zh-hant",
        wait_until="domcontentloaded",
        timeout=60000,
    )
    await page.wait_for_timeout(1200)
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
    print(f"[SEARCH] {query}: {len(results)} results")
    return results


async def main():
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    now = datetime.now(TZ_TAIPEI)
    max_age = int(config.get("max_age_minutes", 60))
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
                    published, evidence = extract_time(f'{result["title"]} {result["snippet"]}', now)
                    age_minutes = round((now - published).total_seconds() / 60, 1) if published else None
                    recent = age_minutes is not None and 0 <= age_minutes <= max_age
                    rows.append({
                        "關鍵字": keyword,
                        "平台": platform,
                        "標題": result["title"],
                        "摘要": result["snippet"],
                        "原始連結": result["url"],
                        "發布時間": published.isoformat() if published else "",
                        "距今分鐘": age_minutes if age_minutes is not None else "",
                        "時間判定": evidence,
                        "分類": "60分鐘內已確認" if recent else "候選商機（時間未確認或超過60分鐘）",
                        "蒐集時間": now.isoformat(),
                    })
                await page.wait_for_timeout(600)
        await browser.close()

    all_results = pd.DataFrame(rows, columns=COLUMNS).drop_duplicates(subset=["原始連結"])
    confirmed = all_results[all_results["分類"] == "60分鐘內已確認"].copy()
    candidates = all_results[all_results["分類"] != "60分鐘內已確認"].copy()

    empty_message = "查無訊息，目前沒有適合的配對"
    confirmed_output = confirmed if not confirmed.empty else pd.DataFrame(
        [{"搜尋狀態": empty_message}]
    )
    candidates_output = candidates if not candidates.empty else pd.DataFrame(
        [{"搜尋狀態": empty_message}]
    )

    OUT.mkdir(exist_ok=True)
    all_results.to_csv(OUT / "全部候選商機.csv", index=False, encoding="utf-8-sig")
    confirmed_output.to_csv(OUT / "60分鐘內已確認.csv", index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(OUT / "串串商機雷達.xlsx", engine="openpyxl") as writer:
        confirmed_output.to_excel(writer, sheet_name="60分鐘內已確認", index=False)
        candidates_output.to_excel(writer, sheet_name="候選商機", index=False)
    (OUT / "搜尋結果說明.txt").write_text(
        empty_message if all_results.empty else f"本次共找到 {len(all_results)} 筆候選資料。",
        encoding="utf-8",
    )

    summary = {
        "collected_at": now.isoformat(),
        "max_age_minutes": max_age,
        "confirmed_recent_count": len(confirmed),
        "candidate_count": len(candidates),
        "total_count": len(all_results),
        "display_message": empty_message if all_results.empty else f"本次共找到 {len(all_results)} 筆候選資料。",
        "note": "候選商機來自公開搜尋結果；未顯示可靠時間者不會冒充60分鐘內的新貼文。"
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())

"""FastAPI service for Google Maps reviews scraping.

Endpoints:
    POST /scrape — extract reviews from one or more Google Maps places
    GET  /health — health check
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from playwright.async_api import async_playwright, Page
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_REVIEWS_DEFAULT = 10
SCROLL_PAUSE_SECONDS = 1.5
PAGE_LOAD_TIMEOUT_MS = 60_000
PAUSE_BETWEEN_PLACES_DEFAULT = 3


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class ScrapeRequest(BaseModel):
    queries: list[str] = Field(..., description="Business names to search on Google Maps")
    max_reviews: int = Field(MAX_REVIEWS_DEFAULT, ge=1, le=1000)
    pause_between_places_sec: int = Field(PAUSE_BETWEEN_PLACES_DEFAULT, ge=0, le=60)


class Review(BaseModel):
    author: str | None = None
    rating: float | None = None
    text: str | None = None
    date: str | None = None
    place_name: str
    place_url: str
    scraped_at: str


class ScrapeResponse(BaseModel):
    status: str
    total_reviews: int
    reviews: list[Review]


# ---------------------------------------------------------------------------
# Scraper helpers
# ---------------------------------------------------------------------------
async def accept_google_consent(page: Page) -> None:
    selectors = [
        'button:has-text("Accept all")',
        'button:has-text("I agree")',
        'button:has-text("Принять все")',
        'button:has-text("Согласен")',
        'form[action*="consent"] button',
        'button[aria-label*="Accept"]',
    ]
    for selector in selectors:
        try:
            button = page.locator(selector).first
            if await button.is_visible(timeout=2000):
                await button.click()
                await page.wait_for_timeout(1500)
                return
        except Exception:
            continue


async def expand_reviews_tab(page: Page) -> bool:
    selectors = [
        'button[role="tab"]:has-text("Reviews")',
        'button[role="tab"]:has-text("Отзывы")',
        'button:has-text("Отзывы")',
        'button:has-text("Reviews")',
        'div[role="tab"]:has-text("Отзывы")',
        'div[role="tab"]:has-text("Reviews")',
        'span:has-text("Отзывы")',
        'span:has-text("Reviews")',
    ]
    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if await loc.count() > 0:
                if await loc.is_visible(timeout=2000):
                    await loc.click()
                    await page.wait_for_timeout(2500)
                    return True
        except Exception:
            continue
    return False


async def scroll_reviews(page: Page, max_reviews: int) -> None:
    scrollable_selector = 'div[role="feed"], div.m6QErb.DxyBCb'
    try:
        panel = page.locator(scrollable_selector).first
        await panel.wait_for(timeout=10_000)
    except Exception:
        logger.warning("Reviews panel not found, skipping scroll.")
        return

    previous_count = 0
    stagnant_rounds = 0

    while True:
        cards = page.locator('div[data-review-id]')
        current_count = await cards.count()
        logger.info(f"Loaded reviews: {current_count}")

        real_count = current_count // 2  # each review appears twice in DOM

        if real_count >= max_reviews:
            break

        if current_count == previous_count:
            stagnant_rounds += 1
            if stagnant_rounds >= 4:
                break
        else:
            stagnant_rounds = 0
        previous_count = current_count

        await panel.evaluate('(el) => el.scrollBy(0, 2000)')
        await page.wait_for_timeout(int(SCROLL_PAUSE_SECONDS * 1000))


async def extract_reviews(page: Page, max_reviews: int) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    cards = page.locator('div[data-review-id]')
    count = await cards.count()

    for i in range(count):
        card = cards.nth(i)
        try:
            author = None
            for sel in ['div.d4r55', 'button[aria-label*="Photo of"]', 'div.WNxzHc']:
                loc = card.locator(sel).first
                if await loc.count() > 0:
                    author = (await loc.inner_text()).strip()
                    if author:
                        break

            rating = None
            rating_el = card.locator('span[role="img"]').first
            if await rating_el.count() > 0:
                aria = await rating_el.get_attribute('aria-label')
                if aria:
                    try:
                        rating = float(aria.split()[0].replace(',', '.'))
                    except ValueError:
                        rating = None

            text = None
            for sel in ['span.wiI7pd', 'div.MyEned span', 'div.MyEned']:
                loc = card.locator(sel).first
                if await loc.count() > 0:
                    t = (await loc.inner_text()).strip()
                    if t:
                        text = t
                        break

            date = None
            for sel in ['span.rsqaWe', 'span.xRkPPb', 'span.dehysf']:
                loc = card.locator(sel).first
                if await loc.count() > 0:
                    d = (await loc.inner_text()).strip()
                    if d:
                        date = d
                        break

            if not text and not author:
                continue

            dedup_key = f'{(author or "").lower()}|{(text or "")[:100]}|{(date or "").lower()}'
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            reviews.append({
                'author': author,
                'rating': rating,
                'text': text,
                'date': date,
                'scraped_at': datetime.utcnow().isoformat(),
            })

            if len(reviews) >= max_reviews:
                break

        except Exception as e:
            logger.warning(f"Error extracting review #{i}: {e}")
            continue

    return reviews


def build_reviews_url(place_url: str) -> str:
    if '!9m1!1b1' in place_url:
        return place_url

    if '/data=' in place_url:
        base, data = place_url.split('/data=', 1)
        if '?' in data:
            data_part, query = data.split('?', 1)
            return f'{base}/data={data_part}!9m1!1b1?{query}'
        return f'{base}/data={data}!9m1!1b1'
    return place_url


async def find_place_by_query(page: Page, query: str) -> str | None:
    url = f'https://www.google.com/maps/search/{quote(query)}'
    logger.info(f"Navigating to: {url}")

    await page.goto(url, timeout=PAGE_LOAD_TIMEOUT_MS, wait_until='domcontentloaded')
    await page.wait_for_timeout(5000)
    await accept_google_consent(page)
    await page.wait_for_timeout(2000)

    if '/maps/place/' in page.url:
        return page.url

    for sel in ['a.hfpxzc', 'a[href*="/maps/place/"]']:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                await loc.click()
                await page.wait_for_timeout(4000)
                return page.url
        except Exception:
            continue

    return None


async def get_place_name(page: Page) -> str:
    try:
        h1 = page.locator('h1').first
        if await h1.count() > 0:
            return (await h1.inner_text()).strip()
    except Exception:
        pass
    return page.url


async def process_place(page: Page, query: str, max_reviews: int) -> list[dict[str, Any]]:
    try:
        place_url = await find_place_by_query(page, query)
        if not place_url:
            logger.warning(f"Could not find place for query: {query!r}")
            return []

        place_name = await get_place_name(page)
        logger.info(f"Place resolved: {place_name} ({place_url})")

        reviews_url = build_reviews_url(place_url)
        if reviews_url != page.url:
            await page.goto(reviews_url, timeout=PAGE_LOAD_TIMEOUT_MS, wait_until='domcontentloaded')
            await page.wait_for_timeout(5000)
            await accept_google_consent(page)
            await page.wait_for_timeout(2000)

        await expand_reviews_tab(page)
        await scroll_reviews(page, max_reviews)
        reviews = await extract_reviews(page, max_reviews)

        for r in reviews:
            r['place_name'] = place_name
            r['place_url'] = place_url

        logger.info(f"Extracted {len(reviews)} reviews for {place_name!r}")
        return reviews

    except Exception as e:
        logger.exception(f"Error processing {query!r}: {e}")
        return []


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Google Maps Reviews Scraper API",
    description="Extract reviews from any Google Maps place",
    version="1.0.0",
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/scrape", response_model=ScrapeResponse)
async def scrape(request: ScrapeRequest) -> ScrapeResponse:
    if not request.queries:
        raise HTTPException(status_code=400, detail="queries cannot be empty")

    all_reviews: list[dict[str, Any]] = []

    async with async_playwright() as playwright:
        launch_args = ['--disable-gpu', '--no-sandbox']
        browser = None
        for channel in ('chrome', 'msedge', None):
            try:
                kwargs: dict = {'headless': True, 'args': launch_args}
                if channel:
                    kwargs['channel'] = channel
                browser = await playwright.chromium.launch(**kwargs)
                logger.info(f"Browser launched with channel={channel!r}")
                break
            except Exception as e:
                logger.warning(f"Launch with channel={channel!r} failed: {e}")
                continue

        if browser is None:
            raise HTTPException(status_code=500, detail="Could not launch any browser")

        context = await browser.new_context(
            locale='en-US',
            user_agent=(
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/122.0.0.0 Safari/537.36'
            ),
            viewport={'width': 1366, 'height': 900},
        )
        page = await context.new_page()

        try:
            for i, query in enumerate(request.queries):
                logger.info(f"--- Place {i + 1}/{len(request.queries)}: {query!r} ---")
                reviews = await process_place(page, query, request.max_reviews)
                all_reviews.extend(reviews)

                if i < len(request.queries) - 1:
                    await page.wait_for_timeout(request.pause_between_places_sec * 1000)
        finally:
            await context.close()
            await browser.close()

    return ScrapeResponse(
        status="success",
        total_reviews=len(all_reviews),
        reviews=[Review(**r) for r in all_reviews],
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
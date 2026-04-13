import time
import random
import urllib.parse
from typing import List, Dict

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _delay(min_s: float = 1.5, max_s: float = 3.5) -> None:
    time.sleep(random.uniform(min_s, max_s))


def scrape_jobs(keywords: str, location: str, max_jobs: int = 25) -> List[Dict]:
    """
    Scrape LinkedIn public job search for the given keywords and location.
    Returns a list of job dicts: title, company, location, url, description.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1366, "height": 768},
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        # Hide the webdriver flag that LinkedIn checks for
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()

        jobs: List[Dict] = []
        try:
            jobs = _collect_jobs(page, keywords, location, max_jobs)
        finally:
            browser.close()

        return jobs


def _collect_jobs(page, keywords: str, location: str, max_jobs: int) -> List[Dict]:
    enc_kw = urllib.parse.quote(keywords)
    enc_loc = urllib.parse.quote(location)
    jobs: List[Dict] = []
    start = 0

    while len(jobs) < max_jobs:
        url = (
            f"https://www.linkedin.com/jobs/search/"
            f"?keywords={enc_kw}&location={enc_loc}&start={start}"
        )
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        _delay(2, 4)

        # Detect login wall
        if "login" in page.url or "authwall" in page.url:
            raise RuntimeError(
                "LinkedIn redirected to a login page. "
                "Try again in a few minutes or use a different network."
            )

        # Wait for job cards to appear
        try:
            page.wait_for_selector(".base-card", timeout=10_000)
        except PlaywrightTimeoutError:
            break  # No results or last page

        cards = page.query_selector_all(".base-card")
        if not cards:
            break

        batch: List[Dict] = []
        for card in cards:
            job = _parse_card(card)
            if job:
                batch.append(job)

        if not batch:
            break

        # Fetch full description for each card
        for job in batch:
            if len(jobs) >= max_jobs:
                break
            if job["url"]:
                job["description"] = _fetch_description(page, job["url"])
            jobs.append(job)
            _delay(1.0, 2.5)

        start += 25
        if len(batch) < 25:
            break  # Reached the last page of results

    return jobs


def _parse_card(card) -> Dict | None:
    try:
        title_el = card.query_selector(".base-search-card__title")
        company_el = card.query_selector(".base-search-card__subtitle")
        location_el = card.query_selector(".job-search-card__location")
        link_el = card.query_selector("a.base-card__full-link")

        return {
            "title": title_el.inner_text().strip() if title_el else "Unknown",
            "company": company_el.inner_text().strip() if company_el else "Unknown",
            "location": location_el.inner_text().strip() if location_el else "",
            "url": link_el.get_attribute("href") if link_el else "",
            "description": "",
        }
    except Exception:
        return None


def _fetch_description(page, url: str) -> str:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        _delay(1.0, 2.0)

        # Expand "Show more" if present
        show_more = page.query_selector("button.show-more-less-html__button")
        if show_more:
            show_more.click()
            _delay(0.5, 1.0)

        for selector in (".show-more-less-html__markup", ".description__text"):
            el = page.query_selector(selector)
            if el:
                return el.inner_text().strip()

        return ""
    except Exception:
        return ""

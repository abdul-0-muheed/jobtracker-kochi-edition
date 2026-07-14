"""
services/linkedin_client.py — Playwright wrapper for LinkedIn session management and scraping.

Session cookies are AES-128 encrypted via Fernet with a PBKDF2-derived key.
No plaintext credentials are ever written to disk.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ── Encryption helpers ────────────────────────────────────────────────────────

def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive a 32-byte Fernet-compatible key from a passphrase via PBKDF2."""
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    raw = kdf.derive(passphrase.encode("utf-8"))
    return base64.urlsafe_b64encode(raw)


def encrypt_cookies(cookies: list[dict], passphrase: str) -> bytes:
    """Serialize and encrypt a list of cookie dicts."""
    from cryptography.fernet import Fernet
    salt = os.urandom(16)
    key  = _derive_key(passphrase, salt)
    f    = Fernet(key)
    payload = json.dumps(cookies).encode("utf-8")
    token = f.encrypt(payload)
    # Prepend salt so we can derive the same key for decryption
    return salt + token


def decrypt_cookies(data: bytes, passphrase: str) -> list[dict]:
    """Decrypt and deserialize cookies."""
    from cryptography.fernet import Fernet, InvalidToken
    salt  = data[:16]
    token = data[16:]
    key   = _derive_key(passphrase, salt)
    f     = Fernet(key)
    try:
        payload = f.decrypt(token)
        return json.loads(payload.decode("utf-8"))
    except InvalidToken:
        raise ValueError("Incorrect passphrase or corrupted session file.")


def save_session(cookies: list[dict], passphrase: str, session_path: Path) -> None:
    """Encrypt and save LinkedIn cookies to disk."""
    encrypted = encrypt_cookies(cookies, passphrase)
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_bytes(encrypted)
    log.info(f"Session saved to {session_path}")


def load_session_cookies(passphrase: str, session_path: Path) -> Optional[list[dict]]:
    """Load and decrypt LinkedIn cookies. Returns None if file doesn't exist."""
    if not session_path.exists():
        return None
    data = session_path.read_bytes()
    return decrypt_cookies(data, passphrase)


# ── Playwright helpers ────────────────────────────────────────────────────────

def _random_delay(min_s: float = 8, max_s: float = 15):
    time.sleep(random.uniform(min_s, max_s))


def _is_rate_limited(page) -> bool:
    return "999" in page.url or page.url.startswith("https://www.linkedin.com/error")


def _is_redirected_to_login(page) -> bool:
    return "/login" in page.url or "/checkpoint" in page.url


def open_browser_with_session(playwright, passphrase: str, session_path: Path):
    """
    Launch Chromium with saved cookies pre-loaded.
    Returns (browser, context, page). Caller is responsible for closing.
    """
    from config import SESSION_DIR
    browser = playwright.chromium.launch(headless=False, slow_mo=50)
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
    )
    cookies = load_session_cookies(passphrase, session_path)
    if cookies:
        context.add_cookies(cookies)
    page = context.new_page()
    return browser, context, page


def do_manual_login(playwright) -> tuple:
    """
    Open a visible Chromium window for the user to log in manually.
    Returns (browser, context, page) after successful login detection.
    """
    browser = playwright.chromium.launch(headless=False, slow_mo=50)
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
    )
    page = context.new_page()
    page.goto("https://www.linkedin.com/login", wait_until="networkidle")
    # Wait for user to log in (URL changes to /feed/)
    log.info("Waiting for user to complete LinkedIn login…")
    page.wait_for_url("**/feed/**", timeout=180_000)  # 3-minute timeout
    log.info("Login detected — session captured.")
    return browser, context, page


def scrape_sent_invitations(page, max_scroll: int = 10) -> list[dict]:
    """
    Scrape sent connection requests from linkedin.com/mynetwork/invitation-manager/sent/
    Returns list of {name, headline, company, profile_url}
    """
    results = []
    page.goto("https://www.linkedin.com/mynetwork/invitation-manager/sent/", wait_until="networkidle")
    _random_delay(3, 6)

    if _is_redirected_to_login(page):
        raise RuntimeError("LinkedIn session expired — please re-authenticate.")
    if _is_rate_limited(page):
        raise RuntimeError("LinkedIn rate limit (999) — aborting.")

    for _ in range(max_scroll):
        page.keyboard.press("End")
        _random_delay(2, 4)

        # Extract invitation cards
        cards = page.query_selector_all("li.invitation-card")
        if not cards:
            cards = page.query_selector_all("[data-view-name='invitation-sent-entity']")

        for card in cards:
            try:
                name_el = card.query_selector(".invitation-card__title, .entity-result__title-text")
                headline_el = card.query_selector(".invitation-card__subtitle, .entity-result__primary-subtitle")
                link_el = card.query_selector("a[href*='/in/']")

                name      = name_el.inner_text().strip()      if name_el      else ""
                headline  = headline_el.inner_text().strip()  if headline_el  else ""
                profile_url = link_el.get_attribute("href")  if link_el      else ""

                # Extract company from headline (e.g., "Senior Dev at Acme Corp")
                company = ""
                if " at " in headline:
                    company = headline.split(" at ", 1)[-1].strip()
                elif " @ " in headline:
                    company = headline.split(" @ ", 1)[-1].strip()

                if name:
                    results.append({
                        "name":        name,
                        "headline":    headline,
                        "company":     company,
                        "profile_url": profile_url,
                    })
            except Exception as e:
                log.debug(f"Card parse error: {e}")

        # Check if "Load more" button exists
        load_more = page.query_selector("button[aria-label*='Load more']")
        if not load_more:
            break
        load_more.click()
        _random_delay(3, 6)

        if _is_rate_limited(page):
            raise RuntimeError("LinkedIn rate limit (999) during invitation scrape.")

    # Deduplicate by profile_url
    seen = set()
    unique = []
    for r in results:
        key = r.get("profile_url") or r.get("name")
        if key and key not in seen:
            seen.add(key)
            unique.append(r)

    log.info(f"Scraped {len(unique)} sent invitations.")
    return unique


def scrape_messages(page, max_threads: int = 50) -> list[dict]:
    """
    Scrape message threads from linkedin.com/messaging/
    Returns list of {recipient_name, recipient_company, thread_url, messages: []}
    """
    results = []
    page.goto("https://www.linkedin.com/messaging/", wait_until="networkidle")
    _random_delay(4, 8)

    if _is_redirected_to_login(page):
        raise RuntimeError("LinkedIn session expired — please re-authenticate.")
    if _is_rate_limited(page):
        raise RuntimeError("LinkedIn rate limit (999) — aborting.")

    threads = page.query_selector_all(".msg-conversation-listitem")
    log.info(f"Found {len(threads)} message threads.")

    for i, thread in enumerate(threads[:max_threads]):
        try:
            name_el = thread.query_selector(".msg-conversation-listitem__participant-names")
            name = name_el.inner_text().strip() if name_el else ""

            thread.click()
            _random_delay(2, 4)

            if _is_rate_limited(page):
                raise RuntimeError("LinkedIn rate limit (999) during message scrape.")

            # Get recipient details from opened thread
            headline_el = page.query_selector(".msg-entity-lockup__headline")
            headline = headline_el.inner_text().strip() if headline_el else ""

            company = ""
            if " at " in headline:
                company = headline.split(" at ", 1)[-1].strip()

            # Get recent messages
            msg_els = page.query_selector_all(".msg-s-event-listitem__body")
            messages = [m.inner_text().strip() for m in msg_els[-5:] if m]   # last 5

            results.append({
                "recipient_name":    name,
                "recipient_company": company,
                "thread_url":        page.url,
                "messages":          messages,
            })
        except RuntimeError:
            raise
        except Exception as e:
            log.debug(f"Thread {i} parse error: {e}")

    return results


def scrape_company_jobs(page, linkedin_url: str) -> list[dict]:
    """
    Scrape job listings from a company's LinkedIn /jobs/ tab.
    Returns list of {title, location, url}
    """
    jobs_url = linkedin_url.rstrip("/") + "/jobs/"
    page.goto(jobs_url, wait_until="networkidle")
    _random_delay(3, 6)

    if _is_redirected_to_login(page) or _is_rate_limited(page):
        return []

    results = []
    job_cards = page.query_selector_all(".job-card-container, .jobs-job-board-list__item")
    for card in job_cards:
        try:
            title_el = card.query_selector(".job-card-list__title, .artdeco-entity-lockup__title")
            loc_el   = card.query_selector(".job-card-container__metadata-item, .artdeco-entity-lockup__caption")
            link_el  = card.query_selector("a")

            title    = title_el.inner_text().strip() if title_el else ""
            location = loc_el.inner_text().strip()   if loc_el   else ""
            url      = link_el.get_attribute("href") if link_el  else ""
            if url and url.startswith("/"):
                url = "https://www.linkedin.com" + url

            if title:
                results.append({"title": title, "location": location, "url": url})
        except Exception as e:
            log.debug(f"Job card parse error: {e}")

    return results

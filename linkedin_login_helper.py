"""
linkedin_login_helper.py — Standalone Playwright login script.

Called by the Flask app as a subprocess:
    python linkedin_login_helper.py <passphrase>

Opens a visible Chromium window → user logs in to LinkedIn →
session cookies are encrypted + saved → window closes.
"""
import sys
import os
import traceback


def main():
    if len(sys.argv) < 2:
        print("Usage: linkedin_login_helper.py <passphrase>")
        input("Press Enter to close...")
        sys.exit(1)

    passphrase = sys.argv[1]

    # Add project root to path so we can import our modules
    project_root = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, project_root)

    print("\n" + "="*60)
    print("  LinkedIn Login Helper")
    print("="*60)
    print("\n  Opening Chromium browser...")
    print("  Please log in to LinkedIn normally.")
    print("  This window will update once you are logged in.\n")

    try:
        from playwright.sync_api import sync_playwright
        from services.linkedin_client import save_session
        from config import SESSION_DIR, load_settings, save_settings
        from datetime import datetime, timezone

        session_file = SESSION_DIR / "linkedin.enc"
        SESSION_DIR.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as pw:
            print("  Launching Chromium...")
            browser = pw.chromium.launch(
                headless=False,
                slow_mo=50,
                args=["--start-maximized"],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                no_viewport=True,
            )
            page = context.new_page()
            print("  Navigating to LinkedIn login page...")
            page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
            print("  Browser is open. Waiting for you to log in...")
            print("  (You have 3 minutes)")

            # Wait until the user lands on feed or home
            page.wait_for_url(
                lambda url: "/feed" in url or "/home" in url,
                timeout=180_000
            )
            print("\n  Login detected! Saving encrypted session...")

            cookies = context.cookies()
            save_session(cookies, passphrase, session_file)
            print(f"  Session saved to: {session_file}")

            # Try to grab display name
            user_name = "LinkedIn User"
            try:
                name_el = page.query_selector(".feed-identity-module__actor-meta .t-bold")
                if name_el:
                    user_name = name_el.inner_text().strip()
            except Exception:
                pass

            browser.close()

        # Update settings
        s = load_settings()
        s["linkedin"]["connected"] = True
        s["linkedin"]["user_name"] = user_name
        s["linkedin"]["last_sync_at"] = datetime.now(timezone.utc).isoformat()
        save_settings(s)

        print(f"\n  SUCCESS! Logged in as: {user_name}")
        print("\n  Return to JobTracker and refresh the LinkedIn Sync page.")
        print("  Your session is saved and encrypted.")
        print("\n" + "="*60)

    except KeyboardInterrupt:
        print("\n  Cancelled by user.")
    except Exception as e:
        print(f"\n  ERROR: {e}")
        print("\n  --- Full traceback ---")
        traceback.print_exc()
        print("\n  Please check that Playwright is installed:")
        print("    python -m pip install playwright")
        print("    python -m playwright install chromium")
        print("="*60)

    input("\n  Press Enter to close this window...")


if __name__ == "__main__":
    main()

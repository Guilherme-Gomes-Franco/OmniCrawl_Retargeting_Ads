#!/usr/bin/env python3
import sys
from playwright.sync_api import sync_playwright
import os

# Usage: python launch_native_chromium.py <path_to_binary> <profile_dir> <url>
# Example: python launch_native_chromium.py /usr/bin/brave-browser /tmp/brave-profile https://example.com
binary_path = sys.argv[1]   # e.g., /usr/bin/brave-browser or /usr/bin/google-chrome
profile_path = sys.argv[2]  # your temp profile path
url = sys.argv[3]

with sync_playwright() as p:
    # Launch native Chromium-family binary (Brave/Chrome) with a persistent profile
    context = p.chromium.launch_persistent_context(
        user_data_dir=profile_path,
        executable_path=binary_path,
        headless=False,
        # Strip standard automation flag
        ignore_default_args=["--enable-automation"],
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    )

    page = context.pages[0] if context.pages else context.new_page()

    # Silo 3: Usability Penalty (Breakage Logging)
    page.on("pageerror", lambda err: print(f"JS_EXCEPTION: {err}"))
    page.on("requestfailed", lambda req: print(f"REQ_FAILED: {req.url} - {req.failure}"))

    # Inject stealth script before any page scripts
    stealth_path = os.path.join(os.path.dirname(__file__), "stealth.js")
    page.add_init_script(path=stealth_path)

    try:
        #print(f"Navigating to {url} with {binary_path}")
        page.goto(url, wait_until="networkidle")
        # Wait 10s for RTB auctions/trackers to fire
        page.wait_for_timeout(10000)
    except Exception as e:
        print(f"Page load error: {e}")
    finally:
        context.close()

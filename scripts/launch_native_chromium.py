#!/usr/bin/env python3
import sys
from playwright.sync_api import sync_playwright

# Usage: python launch_native_chromium.py <path_to_binary> <profile_dir> <url>
binary_path = sys.argv[1]   # e.g., C:\...\brave.exe or chrome.exe
profile_path = sys.argv[2]  # The OmniCrawl TmpProfile path
url = sys.argv[3]

with sync_playwright() as p:
    # launch_persistent_context directly hooks into the binary without chromedriver
    context = p.chromium.launch_persistent_context(
        user_data_dir=profile_path,
        executable_path=binary_path,
        headless=False,
        # Strip all automation flags that Selenium usually forces on
        ignore_default_args=["--enable-automation"],
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check"
        ]
    )
    
    page = context.pages[0] if context.pages else context.new_page()

    # Silo 3: Usability Penalty (Breakage Logging)
    page.on("pageerror", lambda err: print(f"JS_EXCEPTION: {err}"))
    page.on("requestfailed", lambda req: print(f"REQ_FAILED: {req.url} - {req.failure}"))
    
# Inject the robust stealth script before any website code executes
page.add_init_script(path="stealth.js")
    
    try:
        page.goto(url, wait_until="networkidle")
        page.wait_for_timeout(10000) # Wait 10s for RTB auctions/trackers to fire
    except Exception as e:
        print(f"Page load error: {e}")
    finally:
        context.close()
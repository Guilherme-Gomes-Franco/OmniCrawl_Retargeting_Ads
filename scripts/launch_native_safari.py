#!/usr/bin/env python3
import sys
from playwright.sync_api import sync_playwright

# Usage: python launch_native_webkit.py <profile_dir> <url>
# Note: WebKit doesn't need an explicit executable_path because Playwright bundles it.
profile_path = sys.argv[1]  # The OmniCrawl TmpProfile path
url = sys.argv[2]

with sync_playwright() as p:
    # Launch WebKit (Safari's engine) with persistent storage to test ITP
    context = p.webkit.launch_persistent_context(
        user_data_dir=profile_path,
        headless=False,
        # Strip standard automation flags
        ignore_default_args=["--enable-automation"]
    )
    
    page = context.pages[0] if context.pages else context.new_page()

    # Silo 3: Usability Penalty (Breakage Logging)
    page.on("pageerror", lambda err: print(f"JS_EXCEPTION: {err}"))
    page.on("requestfailed", lambda req: print(f"REQ_FAILED: {req.url} - {req.failure}"))
    
   # Inject the robust stealth script before any website code executes
page.add_init_script(path="stealth.js")
    
    try:
        # Navigate and wait for network to settle
        page.goto(url, wait_until="networkidle")
        # Wait 10 seconds to ensure Prebid.js and RTB auctions fully execute
        page.wait_for_timeout(10000) 
    except Exception as e:
        print(f"Page load error: {e}")
    finally:
        context.close()
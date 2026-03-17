#!/usr/bin/env python3
import sys
import os
from playwright.sync_api import sync_playwright

# Usage: python launch_native_firefox.py <path_to_binary> <profile_dir> <url> <enable_rfp>
binary_path = sys.argv[1]
profile_path = sys.argv[2]
url = sys.argv[3]
enable_rfp = sys.argv[4].lower() == 'true'

# Ensure the temporary profile directory exists
os.makedirs(profile_path, exist_ok=True)

# 1. BROWSER-LEVEL STEALTH & HARDENING
# We append these to Firefox's user.js file so they load at the C++ engine level.
user_js_path = os.path.join(profile_path, 'user.js')
with open(user_js_path, 'a') as f:
    # Core stealth: disable the native webdriver flag inside Firefox
    f.write('\nuser_pref("dom.webdriver.enabled", false);\n')
    f.write('user_pref("useAutomationExtension", false);\n')
    
    if enable_rfp:
        # Enable Tor-uplifted Resist Fingerprinting
        f.write('user_pref("privacy.resistFingerprinting", true);\n')
        # Prevent canvas permission popups from freezing the automated crawl
        f.write('user_pref("privacy.resistFingerprinting.autoDeclineNoUserInputCanvasPrompts", true);\n')
        # Spoof language to English (required for standard RFP behavior)
        f.write('user_pref("privacy.spoof_english", 2);\n')

with sync_playwright() as p:
    # 2. LAUNCH FIREFOX NATIVELY
    context = p.firefox.launch_persistent_context(
        user_data_dir=profile_path,
        executable_path=binary_path,
        headless=False,
        # Force Playwright not to pass standard automation flags
        ignore_default_args=["--enable-automation"]
    )
    
    page = context.pages[0] if context.pages else context.new_page()

    # Silo 3: Usability Penalty (Breakage Logging)
    page.on("pageerror", lambda err: print(f"JS_EXCEPTION: {err}"))
    page.on("requestfailed", lambda req: print(f"REQ_FAILED: {req.url} - {req.failure}"))
    
    # 3. JAVASCRIPT-LEVEL STEALTH INJECTION
    # THIS is where the stealth.js file goes. 
    # It ensures the page executes your spoofing script on every new document load.
    page.add_init_script(path="stealth.js")
    
    try:
        print(f"Navigating to {url} (Firefox RFP: {enable_rfp})")
        # Wait until network is idle so dynamic scripts load
        page.goto(url, wait_until="networkidle")
        
        # Wait 10 seconds to allow Real-Time Bidding (RTB) auctions and tracking syncs to fire
        page.wait_for_timeout(10000) 
    except Exception as e:
        print(f"Page load error: {e}")
    finally:
        context.close()
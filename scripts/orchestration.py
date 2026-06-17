#!/usr/bin/env python3
import time
import socket
import threading
from playwright.sync_api import sync_playwright
import argparse
import urllib.request
import tempfile
import subprocess
import csv
import os
import re
from datetime import datetime

# ==========================================================
# 1. THE TCP SYNC SERVER (To handshake with mitmproxy)
# ==========================================================
class CrawlerSyncServer(threading.Thread):
    def __init__(self, host='127.0.0.1', port=50505):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        self.running = True


    def log_progress(browser, phase, site, status, cmp_status, duration):
        log_file = f"/app/data/heartbeat_{browser}.csv"
        file_exists = os.path.isfile(log_file)
        with open(log_file, "a", newline='') as f:
         writer = csv.writer(f)
         if not file_exists:
            writer.writerow(["timestamp", "phase", "site", "status", "cmp_method", "duration_sec"])
        writer.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                phase, site, status, cmp_status, round(duration, 2)
        ])

    def run(self):
        print(f"[Sync Server] Listening for proxy handshakes on {self.host}:{self.port}")
        while self.running:
            try:
                self.server_socket.settimeout(1.0)
                conn, addr = self.server_socket.accept()
                data = conn.recv(1024).decode().strip()
                if data == 'SYN':
                    conn.sendall(b'ACK\n')
                conn.close()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running: print(f"[Sync Server] Error: {e}")

    def stop(self):
        self.running = False
        self.server_socket.close()

# ==========================================================
# 2. BROWSER SETUP & STEALTH INJECTION
# ==========================================================
def create_browser_context(p, browser_type, binary_path, is_hardened):
    """Launches native browser binaries with Playwright and forces Stealth."""
    print(f"\n[Orchestrator] Launching {browser_type} context (Hardened: {is_hardened})...")
    
   # Standard Windows 10 Chrome User-Agent
    SPOOFED_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

     # --- BRAVE STRICT PROFILE HANDLING ---
    if browser_type == "brave" and is_hardened:
        # Dynamically find the project root (one folder above the 'scripts' directory)
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        profile_dir = os.path.join(project_root, "brave_strict_profile")
        
        if not os.path.exists(profile_dir):
            print(f"    [!] WARNING: Brave Strict profile not found at {profile_dir}. Tracking protection may fail.")
        else:
            print(f"    [+] Loading Pre-Warmed Brave Strict Profile from: {profile_dir}")
    else:
        # All other browsers use a disposable temp profile
        profile_dir = tempfile.mkdtemp()

    # ==========================================================
    # CERTIFICATE INJECTION (cert9.db)
    # Prevents the need for ignore_https_errors by natively trusting mitmproxy
    # ==========================================================
    cert_path = os.path.expanduser("~/.mitmproxy/mitmproxy-ca-cert.pem")
    if os.path.exists(cert_path):
        try:
            # 1. Only initialize the database if it doesn't already exist.
            # Running -N on an existing pre-warmed profile causes a password prompt hang.
            if not os.path.exists(os.path.join(profile_dir, "cert9.db")):
                subprocess.check_call([
                    "certutil", "-d", f"sql:{profile_dir}", "-N", "--empty-password"
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Create a temporary empty password file to auto-bypass any prompts
            empty_pwd = tempfile.NamedTemporaryFile(delete=False)
            empty_pwd.write(b"\n")
            empty_pwd.close()
            
            # 2. Inject the mitmproxy certificate as a trusted CA
            subprocess.check_call([
                "certutil", "-A", "-n", "mitmproxy", "-t", "TC,,", 
                "-i", cert_path, "-d", f"sql:{profile_dir}", "-f", empty_pwd.name
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Cleanup the temp file
            os.unlink(empty_pwd.name)
            
            print(f"    [+] Successfully injected mitmproxy cert into cert9.db")
        except FileNotFoundError:
            print("    [-] ERROR: 'certutil' not found! Run: sudo dnf install nss-tools")
        except Exception as e:
            print(f"    [-] ERROR injecting cert: {e}")
    else:
        print(f"    [-] ERROR: mitmproxy cert not found at {cert_path}")

    # Common arguments for all browsers
    launch_kwargs = {
        "user_data_dir": profile_dir,
        "headless": False,
        "proxy": {"server": "http://127.0.0.1:38080"},
        "viewport": {"width": 1920, "height": 1080}
    }
    
    # Ensure Brave uses the correct system binary even if not explicitly passed
    if browser_type == "brave" and not binary_path:
        # Default Linux/Fedora installation path for Brave
        binary_path = "/usr/bin/brave-browser"
        print(f"    [!] No binary path provided for Brave. Defaulting to: {binary_path}")

    if binary_path:
        launch_kwargs["executable_path"] = binary_path

    if browser_type in ["chrome", "brave"]:
        launch_kwargs.update({
            "ignore_https_errors": True,
            "user_agent": SPOOFED_UA,
            "ignore_default_args": ["--enable-automation"],
            "args": [
                "--disable-blink-features=AutomationControlled", 
                "--test-type",
                "--no-default-browser-check",
                "--disable-search-engine-choice-screen",
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
        })
        context = p.chromium.launch_persistent_context(**launch_kwargs)
        
    elif browser_type == "firefox":
        user_js_path = os.path.join(profile_dir, 'user.js')
        with open(user_js_path, 'a') as f:
            f.write('\nuser_pref("dom.webdriver.enabled", false);\n')
            f.write('user_pref("useAutomationExtension", false);\n')
            f.write('user_pref("media.eme.enabled", true);\n')
            f.write('user_pref("browser.eme.ui.enabled", false);\n')
            f.write('user_pref("media.gmp-widevinecdm.visible", true);\n')
            f.write('user_pref("media.gmp-widevinecdm.enabled", true);\n')

            if is_hardened:
                f.write('user_pref("privacy.resistFingerprinting", true);\n')
                f.write('user_pref("privacy.resistFingerprinting.autoDeclineNoUserInputCanvasPrompts", true);\n')
                f.write('user_pref("privacy.spoof_english", 2);\n') 
                
        launch_kwargs.update({"ignore_default_args": ["--enable-automation"]})
        context = p.firefox.launch_persistent_context(**launch_kwargs)
    
    elif browser_type == "webkit":
        launch_kwargs.update({
            "ignore_https_errors": True,
            "user_agent": SPOOFED_UA,
            "ignore_default_args": ["--enable-automation"],
            "args": ["--disable-service-workers"]
        })
        context = p.webkit.launch_persistent_context(**launch_kwargs)
    else:
        raise ValueError("Invalid browser type")

    # Inject Stealth JS into all pages to prevent Automation Bias (Section 3.3.3)
    stealth_path = os.path.join(os.path.dirname(__file__), "stealth.js")
    try:
        with open(stealth_path, "r") as f:
            stealth_js = f.read()
            context.add_init_script(stealth_js)
    except FileNotFoundError:
        print(f"[Warning] {stealth_path} not found. Bypassing JS stealth injection.")

    return context

# ==========================================================
# 3. THE 3-PHASE CAUSAL INFERENCE WORKFLOW (Figure 4.2)
# ==========================================================
def run_crawl_phase(context, phase_name, browser_id, target_sites, sync_port):
    """Executes a single phase by driving the browser and commanding the proxy."""
    print(f"\n=== Starting {phase_name} ({browser_id}) ===")

    # Use ONE tab to prevent page.close() IPC deadlocks
    page = context.new_page()

    # --- DEFENSE VERIFICATION CHECK ---
    try:
        if browser_type == "firefox":
            tz = page.evaluate("Intl.DateTimeFormat().resolvedOptions().timeZone")
            print(f"    [+] Defense Check: Firefox Timezone is '{tz}' (RFP forces UTC)")
        elif browser_type == "brave":
            is_brave = page.evaluate("(navigator.brave && navigator.brave.isBrave) ? true : false")
            print(f"    [+] Defense Check: Browser is Brave = {is_brave}")
    except: pass
    # ----------------------------------
    
    try:
        page.route("**/*.{mp4,webm,ogg,mov,avi}", lambda route: route.abort())
    except:
        pass

    for site in target_sites:
        print(f" -> Visiting: {site}")
        start_api = f"http://240.240.240.240/start?url={site}&browser={browser_id}_{phase_name}&sync_host=127.0.0.1&sync_port={sync_port}&scroll=true"
        
        try:
            # --- 1. NAVIGATION BLOCK ---
            try:
                page.goto(start_api, wait_until="commit", timeout=15000)
                page.wait_for_function("window.location.hostname !== '240.240.240.240'", timeout=20000)
                page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception as e:
                print(f"    [!] Timeout or Error on {site}. Skipping to next site...")
                continue # Move to the next site in SEEDER_SITES (finally block will still execute to stop proxy)

            print("    [+] Arrived at target. Waiting 15s for RTB auctions...")

            # ==========================================
            # 2.5 AUTO-ACCEPT COOKIES (API-First + DOM Fallback)
            # ==========================================
            print("    [+] Hunting for CMP banners...")
            try:
                banner_clicked = False
                
                # --- FPTrace API-Level Consent Injection ---
                api_consent_js = """
                () => {
                    try {
                        if (typeof window.OneTrust !== 'undefined' && window.OneTrust.AllowAll) {
                            window.OneTrust.AllowAll();
                            let ot = document.getElementById('onetrust-banner-sdk');
                            if (ot) ot.style.display = 'none';
                            return 'OneTrust API';
                        }
                        if (typeof window.Didomi !== 'undefined' && window.Didomi.setUserAgreeToAll) {
                            window.Didomi.setUserAgreeToAll();
                            let didomi = document.getElementById('didomi-host');
                            if (didomi) didomi.style.display = 'none';
                            return 'Didomi API';
                        }
                        if (typeof window.Cookiebot !== 'undefined' && window.Cookiebot.dialog) {
                            let cb = document.getElementById('CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll');
                            if (cb) { cb.click(); return 'Cookiebot API'; }
                        }
                    } catch (e) {}
                    return null;
                }
                """
                
                # Fire the API override instantly
                try:
                    api_result = page.evaluate(api_consent_js)
                    if api_result:
                        print(f"    [+] CMP Banner Accepted instantly via {api_result}!")
                        banner_clicked = True
                except:
                    pass

                # --- DOM-Level Fallback (For Quantcast/SourcePoint) ---
                if not banner_clicked:
                    cmp_selectors = (
                        "#onetrust-accept-btn-handler, #accept-recommended-btn-handler, "
                        "button.sp_choice_type_11, button.sp_choice_type_agree, "
                        "button[title*='happy' i], button[title*='Agree' i], "
                        ".didomi-continue-button, .qc-cmp2-b-agree, "
                        "#uc-btn-accept-banner, button#accept-btn, "
                        ".qc-cmp2-summary-buttons button[mode='primary'], "
                        ".epaas-consent-drawer-accept-all, #truste-consent-button, .truste-button1, .trustarc-agree-btn"
                    )
                    
                    accept_regex = re.compile(
                        r"^(?!(.*(previous|quote|reading|policy|settings|manage|details))).*\b(Accept All|Accept all cookies|Accept cookies|I Accept|I agree|Yes, I.m happy|Allow All|Allow all|Aceitar todos|Aceitar todas|Aceitar tudo|Permitir todos|Aceitar|Concordo|Agree|Accept|Consent|Continue|Confirm)\b.*$", 
                        re.IGNORECASE
                    )
                    
                    page.mouse.wheel(0, 300)
                    time.sleep(1)
                    
                    for attempt in range(12): 
                        if banner_clicked: break                          
                        
                        for i, frame in enumerate(page.frames):
                            if banner_clicked: break
                            is_main_page = (i == 0)
                            
                            # Optimization: Don't scan ad iframes
                            if not is_main_page:
                                f_url = frame.url.lower()
                                if not any(kw in f_url for kw in ["sourcepoint", "privacy", "consent", "sp_message", "trustarc", "cookie", "cmp", "consent-pref", "truste"]):
                                    continue

                            try:
                                # 1. Try Specific CSS Selectors first
                                loc = frame.locator(cmp_selectors).first
                                if loc.count() > 0 and loc.is_visible():
                                    btn_text = loc.inner_text().strip() or loc.get_attribute("title") or "CSS Match"
                                    print(f"    [+] CMP Clicked: '{btn_text}' (Frame: {i})")
                                    try: loc.click(timeout=1000, force=True, no_wait_after=True)
                                    except: loc.evaluate("node => node.click()")
                                    banner_clicked = True
                                    break
                                    
                                # 2. Try Text Regex (with Length Safety)
                                all_potential = frame.locator("button, a, div[role='button']")
                                for j in range(all_potential.count()):
                                    candidate = all_potential.nth(j)
                                    if candidate.is_visible():
                                        raw_text = candidate.inner_text().strip()
                                        
                                        # SAFETY CHECK: Consent buttons are short. 
                                        if 2 <= len(raw_text) < 35: 
                                            if accept_regex.search(raw_text):
                                                print(f"    [+] CMP Clicked via Regex: '{raw_text}' (Frame: {i})")
                                                try: candidate.click(timeout=1000, force=True, no_wait_after=True)
                                                except: candidate.evaluate("node => node.click()")
                                                banner_clicked = True
                                                break
                            except: pass
                        if not banner_clicked:
                            time.sleep(2) 
                            
                if banner_clicked:
                    time.sleep(3) # Wait for cookies to drop
                else:
                    print("    [-] No banner found/clickable via API or DOM.")

            except Exception as e:
                print(f"    [-] Banner clicker encountered an error: {e}")
            # ==========================================

            # 3. Simulate human behavior
            try:
                # We use page.mouse for authentic hardware-level events to fool WAFs
                page.mouse.move(500, 200, steps=10)
                time.sleep(0.5) # Using Python sleep avoids Playwright IPC timeouts
                page.mouse.wheel(0, 600)  
                time.sleep(0.5)
                page.mouse.move(600, 400, steps=10)
            except Exception as e:
                # If WebKit locks up during the mouse move, we safely catch it and move on
                pass

            # 4. Wait 10 seconds for RTB auctions
            time.sleep(10)
            
        except Exception as e:
            print(f"[Error] Failed during execution of {site}: {e}")
            
        finally:
            # 5. Stop logging (Out-of-Band Python Request)
            try:
                proxy_support = urllib.request.ProxyHandler({'http': 'http://127.0.0.1:38080'})
                opener = urllib.request.build_opener(proxy_support)
                opener.open("http://240.240.240.240/stop", timeout=5)
                time.sleep(1.5)
                print("    [+] Proxy logging stopped cleanly.")
            except: pass
            
            # 6. THE DOM NUKE: Instantly frees RAM without deadlocking WebKit
            try:
                page.evaluate("setTimeout(() => { document.body.innerHTML = ''; }, 0)")
                time.sleep(1)
            except: pass

def main():
    parser = argparse.ArgumentParser(description="ETR Causal Inference Orchestrator")
    parser.add_argument("--browser", choices=["chrome", "brave", "firefox", "webkit"], required=True)
    parser.add_argument("--binary", help="Path to native browser executable (Chrome/Brave/Firefox)", default="")
    parser.add_argument("--hardened", action="store_true", help="Enable Firefox RFP or Brave Strict")
    args = parser.parse_args()

    # Define your domains for the Causal Workflow
    # ==========================================================
    # SEEDER SITES: Building the "Affluent Consumer" Persona
    # Target: High-Net-Worth (HNW) segment with interest in 
    # Insurance, Luxury Retail, and Automotive.
    # ==========================================================
    SEEDER_SITES = [
        # --- Segment 1: Financial & Insurance (High CPM) ---
        "https://www.geico.com",
        "https://www.progressive.com",
        "https://www.statefarm.com",
        "https://www.allstate.com",
        "https://www.nerdwallet.com",
        "https://www.investopedia.com",
        
        # --- Segment 2: Automotive Research (High Intent) ---
        "https://www.kbb.com",
        "https://www.autotrader.com",
        
        # --- Segment 3: Luxury Retail & Lifestyle (Aggressive Retargeting) ---
        "https://www.architecturaldigest.com",
        "https://www.robbreport.com",
        
        # --- Segment 4: High-End Travel & Real Estate (Soft Targets) ---
        "https://www.fourseasons.com",
        "https://www.ritzcarlton.com",
        "https://www.remax.com",
        "https://www.century21.com",
    ]
    
    # Publisher sites: Ad-heavy sites where we measure the RTB auctions (CPMs)
    PUBLISHER_SITES =[
        "https://www.cnn.com",
        "https://www.theguardian.com",
        "https://www.independent.co.uk",
        "https://www.nytimes.com",
        ]

    sync_port = 50505
    sync_server = CrawlerSyncServer(port=sync_port)
    sync_server.start()
    
    try:
        with sync_playwright() as p:
            # =========================================================
            # PHASE 1: Persona Training & Baseline Measurement
            # =========================================================
            context = create_browser_context(p, args.browser, args.binary, args.hardened)
            
            print("\n=== [Phase 1A] Building High-Value Persona ===")
            # We visit seeder sites to drop 3rd-party cookies & fingerprints into the network
            run_crawl_phase(context, "Phase1A_Training", args.browser, SEEDER_SITES, sync_port)
            
            print("\n=== [Phase 1B] Establishing Baseline CPM ===")
            # We visit the publishers NOW to record how much DSPs bid for our "Known" High-Value Persona
            run_crawl_phase(context, "Phase1B_PreBreak", args.browser, PUBLISHER_SITES, sync_port)
            
            # =========================================================
            # PHASE 2: The Identity Break
            # =========================================================
            print("\n=== [Phase 2] Executing Identity Break ===")
            print("Closing browser context to flush Cookies, localStorage, and IndexedDB...")
            context.close()  # Total clearance of all Stateful tracking data
            time.sleep(2)    # Allow OS to clear file locks
            
            # =========================================================
            # PHASE 3: Efficacy Measurement ("The Anonymous State")
            # =========================================================
            # Re-launch with the exact same binary and stealth config.
            # Trackers must rely solely on Stateless Fingerprinting to re-identify us.
            context = create_browser_context(p, args.browser, args.binary, args.hardened)

            # Force Playwright to throw an error instead of hanging infinitely if the browser crashes
            context.set_default_timeout(30000)
            
            print("\n=== [Phase 3] Measuring Defense Efficacy ===")
            # Revisit the exact same publishers. If CPMs are just as high as Phase 1B, tracking persisted!
            run_crawl_phase(context, "Phase3_PostBreak", args.browser, PUBLISHER_SITES, sync_port)
            
            context.close()

    except KeyboardInterrupt:
        print("\n[Orchestrator] Crawl aborted by user. Cleaning up ports...")       
    except Exception as e:
        print(f"[Error] Orchestration failed: {e}")
    finally:
        sync_server.stop()
        print("\n[Orchestrator] Causal Inference crawl complete! Logs saved to OmniCrawl database.")

if __name__ == "__main__":
    main()
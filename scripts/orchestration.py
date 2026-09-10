#!/usr/bin/env python3
from email import parser
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
import shutil


# Determine where we are: Docker uses /app, Local uses the script's parent folder
if os.path.exists("/app"):
    PROJECT_ROOT = "/app"
    DATA_DIR = "/app/data"
else:
    # On your Fedora machine, this is the folder containing 'scripts' and 'data'
    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    DATA_DIR = os.path.join(PROJECT_ROOT, "data")

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)
print(f"[*] Environment Detected. Project Root: {PROJECT_ROOT} | Data Dir: {DATA_DIR}")

def log_progress(worker_id, phase, site, status, cmp_status, duration):
    log_file = os.path.join(DATA_DIR, f"heartbeat_{worker_id}.csv")
    try:
        file_exists = os.path.isfile(log_file)
        with open(log_file, "a", newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["timestamp", "phase", "site", "status", "cmp_method", "duration_sec"])
            writer.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                phase, site, status, cmp_status, round(duration, 2)
            ])
    except Exception as e:
        print(f"    [!] Internal Logging Error: {e}")

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
def create_browser_context(p, browser_type, binary_path, is_hardened, proxy_port):
    """Launches native browser binaries with Playwright and forces Stealth."""
    print(f"\n[Orchestrator] Launching {browser_type} context (Hardened: {is_hardened})...")
    
   # Standard Windows 10 Chrome User-Agent
    SPOOFED_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    run_profile_dir = tempfile.mkdtemp()

     # --- BRAVE STRICT PROFILE HANDLING ---
    if browser_type == "brave" and is_hardened:
        # Dynamically find the project root (one folder above the 'scripts' directory)
        template_dir = os.path.join(PROJECT_ROOT, "brave_strict_profile")
        
        if os.path.exists(template_dir):
            print(f"    [+] Cloning Brave Strict Template to: {run_profile_dir}")

            # --- FIX: IGNORE BROWSER LOCK FILES ---
            # We ignore files that cause shutil to crash (locks, sockets, etc.)
            ignore_func = shutil.ignore_patterns(
                'SingletonLock', 'SingletonSocket', 'SingletonCookie', 
                'parent.lock', 'lock', '.parentlock', 'BrowserMetrics*', 'Crashpad'
            )
            # We copy only the contents, so the browser starts with pre-set Shields
            # dirs_exist_ok=True is used to copy into the already created tempdir
            shutil.copytree(template_dir, run_profile_dir, dirs_exist_ok=True, ignore=ignore_func)

            for cert_file in ["cert9.db", "key4.db", "pkcs11.txt"]:
                target = os.path.join(run_profile_dir, cert_file)
            if os.path.exists(target):
                os.remove(target)
        else:
            print(f"    [!] WARNING: Brave Template not found. Starting clean.")
    # All other browsers use a disposable temp profile
    profile_dir = run_profile_dir

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
        "proxy": {"server": f"http://127.0.0.1:{proxy_port}"},
        "viewport": {"width": 1920, "height": 1080}
    }
    
    # 1. If no binary_path was provided, only then search for it
    if browser_type == "brave" and not binary_path:
        binary_path= "/usr/lib/brave-browser/brave"

    # 2. Use the binary_path passed from entrypoint.sh if it exists
        if binary_path and os.path.exists(binary_path):
            print(f"    [+] Using provided binary path: {binary_path}")
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
                "--disable-dev-shm-usage",
                "--no-first-run",           # Skip welcome screens
                "--no-welcome",             # Skip welcome screens
                "--disable-features=BraveRewards,BraveNews", # Disable Brave extras
                "--disable-brave-update",        # Stop Brave update checks
                "--restore-last-session=false",  # Force clean start
                  # --- NEW STABILITY FLAGS ---
                "--password-store=basic",       # <--- Prevents Keyring crash
                "--use-mock-keychain",          # <--- Prevents Keyring crash
                "--disable-gpu",                # Prevents 3D acceleration crashes
                "--no-zygote",                 # Disables the internal process manager
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
        })
        context = p.webkit.launch_persistent_context(**launch_kwargs)
    else:
        raise ValueError("Invalid browser type")

    # Inject Stealth JS into all pages to prevent Automation Bias (Section 3.3.3)
    stealth_path = os.path.join(PROJECT_ROOT, "scripts", "stealth.js")
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
def run_crawl_phase(context, phase_name, browser_id, target_sites, sync_port, proxy_port):
    """Executes a single phase by driving the browser and commanding the proxy."""
    print(f"\n=== Starting {phase_name} ({browser_id}) ===")

    if len(context.pages) > 0:
            page = context.pages[0]
    else:
            page = context.new_page()
    
    # Close any other trailing tabs that might have opened
    for p in context.pages[1:]:
        try: p.close()
        except: pass

    # Global timeout for any single playwright action (30s)
    page.set_default_timeout(30000)

    # Safe way to "disable" Service Workers for all browsers including WebKit
    try:
        # We abort any request to register a service worker
        page.route("**/sw.js", lambda route: route.abort())
        page.route("**/service-worker.js", lambda route: route.abort())
        page.route("**/*.{mp4,webm,ogg,mov,avi}", lambda route: route.abort())
    except:
        pass

    js_errors = []

    # 1. Catch Fatal Page Crashes
    def on_page_error(exception):
        msg = getattr(exception, 'message', str(exception))
        print(f"[BREAKAGE] Fatal Error: {msg[:100]}...") 
        js_errors.append({
            "message": msg,
            "stack": getattr(exception, 'stack', '') or ""
        })

    # 2. Catch Console Errors (This is where 99% of ad/tracker breakage lives)
    def on_console(msg):
        if msg.type == "error":
            # Filter out standard 404s/CSS warnings to keep the DB clean, 
            # focusing only on script/tracker failures.
            if "ERR_BLOCKED" in msg.text or "TypeError" in msg.text or "Unhandled" in msg.text or "Failed to load" in msg.text:
                print(f"[BREAKAGE] Console: {msg.text[:100]}...")
                js_errors.append({
                    "message": f"Console Error: {msg.text}",
                    "stack": msg.location.get('url', 'unknown_source')
                })

    # 3. Catch Blocked Tracking Requests
    def on_request_failed(request):
        if request.resource_type in ["script", "xhr", "fetch"]:
            err = request.failure
            if err:
                # We don't print these to avoid terminal spam, but we log them for your thesis
                js_errors.append({
                    "message": f"Blocked/Failed Request: {request.url}",
                    "stack": err
                })

    # Attach all 3 listeners to the page
    page.on("pageerror", on_page_error)
    page.on("console", on_console)
    page.on("requestfailed", on_request_failed)
    # --------------------------------------

    for site in target_sites:
        start_time = time.perf_counter()

        status = "SUCCESS"
        cmp_result = "NONE"

        js_errors.clear()   

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
                status = f"NAV_ERROR: {str(e)[:30]}"
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
                        cmp_result = api_result
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
                                    cmp_result = "CSS Selector"
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
                                                cmp_result = "Regex Match"
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
                pass

            # 4. Wait 15 seconds for RTB auctions
            time.sleep(15)
            
        except Exception as e:
            print(f"[Error] Failed during execution of {site}: {e}")
            status = f"NAV_ERROR: {str(e)[:30]}"
            
        finally:

              # Calculate duration
            duration = time.perf_counter() - start_time

            # UNIQUE WORKER ID: browser_port (e.g., chrome_38080)
            worker_id = f"{browser_id}_{proxy_port}"

            #For debugging, print the status and duration
            log_progress(worker_id, phase_name, site, status, cmp_result, duration)

             # SEND JS ERRORS VIA NATIVE PYTHON POST ---
            if js_errors:
                print(f"    [+] Flushing {len(js_errors)} JS exceptions to proxy...")
                try:
                    import json
                    # Construct clean JSON payload
                    payload = json.dumps({"type": "JS_EXCEPTIONS", "data": js_errors}).encode('utf-8')
                    
                    req = urllib.request.Request("http://240.240.240.240/js_error", data=payload, headers={'Content-Type': 'application/json'})
                    proxy_support = urllib.request.ProxyHandler({'http': f'http://127.0.0.1:{proxy_port}'})
                    opener = urllib.request.build_opener(proxy_support)
                    opener.open(req, timeout=5)
                except Exception as e:
                    print(f"    [-] Failed to flush JS exceptions: {e}")

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
                  # Navigating to about:blank is safer than page.close() in WebKit/Brave
                page.goto("about:blank", timeout=5000)
            except: pass

def main():
    parser = argparse.ArgumentParser(description="ETR Causal Inference Orchestrator")
    parser.add_argument("--browser", choices=["chrome", "brave", "firefox", "webkit"], required=True)
    parser.add_argument("--binary", help="Path to native browser executable (Chrome/Brave/Firefox)", default="")
    parser.add_argument("--hardened", action="store_true", help="Enable Firefox RFP or Brave Strict")
    parser.add_argument("--start-idx", type=int, default=0)
    parser.add_argument("--end-idx", type=int, default=None)
    parser.add_argument("--proxy-port", type=int, default=38080)
    args = parser.parse_args()

    mode_str = "hardened" if args.hardened else "baseline"
    # Example: brave_hardened or firefox_baseline
    browser_label = f"{args.browser}_{mode_str}" 

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
    "https://www.pinterest.com",
    "https://www.nytimes.com",
    "https://www.cnn.com",
    "https://www.theguardian.com",
    "https://www.weather.com",
    "https://www.springer.com",
    "https://www.tinyurl.com",
    "https://www.nature.com",
    "https://www.dailymail.co.uk",
    "https://www.globo.com",
    "https://www.businessinsider.com",
    "https://www.quora.com",
    "https://www.foxnews.com",
    "https://www.indiatimes.com",
    "https://www.wired.com",
    "https://www.usatoday.com",
    "https://www.target.com",
    "https://www.britannica.com",
    "https://www.accuweather.com",
    "https://www.cbsnews.com",
    "https://www.cnet.com",
    "https://www.ted.com",
    "https://www.people.com",
    "https://www.hbr.org",
    "https://www.daum.net",
    "https://www.investopedia.com",
    "https://www.healthline.com",
    "https://www.genius.com",
    "https://www.theatlantic.com",
    "https://www.nypost.com",
    "https://www.quizlet.com",
    "https://www.huffpost.com",
    "https://www.sofascore.com",
    "https://www.moneycontrol.com",
    "https://www.marca.com",
    "https://www.tabelog.com",
    "https://www.clarin.com",
    "https://www.huffingtonpost.com",
    "https://www.elconfidencial.com",
    "https://www.cricbuzz.com",
    "https://www.vnexpress.net",
    "https://www.biomedcentral.com",
    "https://www.donga.com",
    "https://www.buzzfeed.com",
    "https://www.haberler.com",
    "https://www.ruliweb.com",
    "https://www.syosetu.com",
    "https://www.3bmeteo.com",
    "https://www.netkeiba.com",
    "https://www.sondakika.com",
    "https://www.newyorker.com",
    "https://www.cronista.com",
    "https://www.bikewale.com",
    "https://www.russianfood.com",
    "https://www.chordtela.com",
    "https://www.zdnet.com",
    "https://www.yallakora.com",
    "https://www.sciencemag.org",
    "https://www.arstechnica.com",
    "https://www.gizmodo.com",
    "https://www.investing.com",
    "https://www.mashable.com",
    "https://www.euronews.com",
    "https://www.science.org",
    "https://www.mirror.co.uk",
    "https://www.wunderground.com",
    "https://www.timeanddate.com",
    "https://www.medicalnewstoday.com",
    "https://www.smh.com.au",
    "https://www.slate.com",
    "https://www.dailymail.com",
    "https://www.entrepreneur.com",
    "https://www.guardian.co.uk",
    "https://www.express.co.uk",
    "https://www.ticketmaster.com",
    "https://www.scmp.com",
    "https://www.wetransfer.com",
    "https://www.aarp.org",
    "https://www.theglobeandmail.com",
    "https://www.gamespot.com",
    "https://www.thetimes.co.uk",
    "https://www.vogue.com",
    "https://www.thehindu.com",
    "https://www.asahi.com",
    "https://www.thedailybeast.com",
    "https://www.ctvnews.ca",
    "https://www.dictionary.com",
    "https://www.tmz.com",
    "https://www.fool.com",
    "https://www.nfl.com",
    "https://www.theregister.com",
    "https://www.walgreens.com",
    "https://www.allrecipes.com",
    "https://www.lifehacker.com",
    "https://www.straitstimes.com",
    "https://www.vanityfair.com",
    "https://www.lavanguardia.com",
    "https://www.nzherald.co.nz",
    "https://www.thetimes.com",
    "https://www.economictimes.com",
    "https://www.cbssports.com",
    "https://www.foxbusiness.com",
    "https://www.jpost.com",
    "https://www.nhl.com",
    "https://www.flightaware.com",
    "https://www.urbandictionary.com",
    "https://www.stuff.co.nz",
    "https://www.standard.co.uk",
    "https://www.bostonglobe.com",
    "https://www.news24.com",
    "https://www.rte.ie",
    "https://www.poshmark.com",
    "https://www.thestar.com",
    "https://www.coindesk.com",
    "https://www.verywellhealth.com",
    "https://www.tunein.com",
    "https://www.verywellmind.com",
    "https://www.livemint.com",
    "https://www.boardgamegeek.com",
    "https://www.sportskeeda.com",
    "https://www.travelandleisure.com",
    "https://www.marthastewart.com",
    "https://www.thesaurus.com",
    "https://www.detik.com",
    "https://www.southernliving.com",
    "https://www.archdaily.com",
    "https://www.patch.com",
    "https://www.rome2rio.com",
    "https://www.searchenginejournal.com",
    "https://www.everydayhealth.com",
    "https://www.theregister.co.uk",
    "https://www.eatingwell.com",
    "https://www.kompas.com",
    "https://www.gq.com",
    "https://www.ew.com",
    "https://www.mundodeportivo.com",
    "https://www.drugs.com",
    "https://www.khaleejtimes.com",
    "https://www.alexa.com",
    "https://www.meteoblue.com",
    "https://www.theage.com.au",
    "https://www.aap.org",
    "https://www.kakaku.com",
    "https://www.theweathernetwork.com",
    "https://www.outlookindia.com",
    "https://www.ixbt.com",
    "https://www.breitbart.com",
    "https://www.lapresse.ca",
    "https://www.serverwatch.com",
    "https://www.oneindia.com",
    ]

    sync_port = 50505
    sync_server = CrawlerSyncServer(port=sync_port)
    sync_server.start()
    
    try:
        with sync_playwright() as p:
            # =========================================================
            # PHASE 1: Persona Training & Baseline Measurement
            # =========================================================
            context = create_browser_context(p, args.browser, args.binary, args.hardened, args.proxy_port)
            
            print("\n=== [Phase 1A] Building High-Value Persona ===")
            # We visit seeder sites to drop 3rd-party cookies & fingerprints into the network
            run_crawl_phase(context, "Phase1A_Training", browser_label, SEEDER_SITES, sync_port, args.proxy_port)
            
            print("\n=== [Phase 1B] Establishing Baseline CPM ===")
            # We visit the publishers NOW to record how much DSPs bid for our "Known" High-Value Persona
            if args.end_idx is None or args.end_idx > len(PUBLISHER_SITES):
                args.end_idx = len(PUBLISHER_SITES)
            if args.start_idx >= len(PUBLISHER_SITES):
                args.start_idx = 0
            current_publishers = PUBLISHER_SITES[args.start_idx:args.end_idx]

            run_crawl_phase(context, "Phase1B_PreBreak", browser_label, current_publishers, sync_port, args.proxy_port)
            
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
            context = create_browser_context(p, args.browser, args.binary, args.hardened, args.proxy_port)

            # Force Playwright to throw an error instead of hanging infinitely if the browser crashes
            context.set_default_timeout(30000)
            
            print("\n=== [Phase 3] Measuring Defense Efficacy ===")
            # Revisit the exact same publishers. If CPMs are just as high as Phase 1B, tracking persisted!
            run_crawl_phase(context, "Phase3_PostBreak", browser_label, current_publishers, sync_port, args.proxy_port)
            
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
#!/usr/bin/env python3
import time
import socket
import threading
from playwright.sync_api import sync_playwright
import argparse
import urllib.request
import tempfile
import subprocess
import sys
import os

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
def create_browser_context(p, browser_type, binary_path, is_hardened):
    """Launches native browser binaries with Playwright and forces Stealth."""
    print(f"\n[Orchestrator] Launching {browser_type} context (Hardened: {is_hardened})...")
    
    # Standard Windows 10 Chrome User-Agent to blend in
    SPOOFED_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    profile_dir = tempfile.mkdtemp()

      # ==========================================================
    # CERTIFICATE INJECTION (cert9.db)
    # Prevents the need for ignore_https_errors by natively trusting mitmproxy
    # ==========================================================
    cert_path = os.path.expanduser("~/.mitmproxy/mitmproxy-ca-cert.pem")
    if os.path.exists(cert_path):
        try:
            # 1. Initialize an empty NSS database in the temporary profile
            subprocess.check_call([
                "certutil", "-d", f"sql:{profile_dir}", "-N", "--empty-password"
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # 2. Inject the mitmproxy certificate as a trusted CA (Trust flags: TC,,)
            subprocess.check_call([
                "certutil", "-A", "-n", "mitmproxy", "-t", "TC,,", 
                "-i", cert_path, "-d", f"sql:{profile_dir}"
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
    
    # Only supply executable_path if we are using Brave
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
                "--disable-search-engine-choice-screen"
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
            "ignore_default_args": ["--enable-automation"]
        })
        context = p.webkit.launch_persistent_context(**launch_kwargs)

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
    page = context.pages[0] if context.pages else context.new_page()

    # Usability/Breakage Logging (Section 4.3.5)
    page.on("pageerror", lambda err: print(f"[BREAKAGE LOG] JS Exception: {err}"))

    for site in target_sites:
        print(f" -> Visiting: {site}")
        start_api = f"http://240.240.240.240/start?url={site}&browser={browser_id}_{phase_name}&sync_host=127.0.0.1&sync_port={sync_port}&scroll=true"
        
        try:
            # 1. Trigger the proxy. We EXPECT an exception here because the proxy's 
            # JS redirect will cancel Playwright's navigation promise.
            try:
                page.goto(start_api, wait_until="commit", timeout=10000)
            except Exception:
                pass # Ignore the navigation aborted error
            
            # 2. Wait for the actual target site (e.g., CNN) to start rendering
            try:
                page.wait_for_load_state("domcontentloaded", timeout=30000)
            except Exception:
                pass # Proceed even if the page is heavy and slow
                
            print("    [+] Arrived at target. Waiting 15s for RTB auctions...")

            # ==========================================
            # 2.5 AUTO-ACCEPT COOKIES (Native JS Frame-Piercing)
            # ==========================================
            print("    [+] Hunting for CMP banners (Fast JS Evaluation)...")
            try:
                banner_clicked = False
                
                # This raw JavaScript executes natively inside the browser engine,
                # bypassing Playwright's Python IPC deadlock completely.
                js_clicker = """
                () => {
                    // 1. Try CSS Selectors (Zero false positives)
                    const selectors = "#onetrust-accept-btn-handler, button.sp_choice_type_11, .didomi-continue-button, .qc-cmp2-b-agree, #uc-btn-accept-banner, button#accept-btn, .qc-cmp2-summary-buttons button[mode='primary']";
                    const btn = document.querySelector(selectors);
                    if (btn) { btn.click(); return true; }
                    
                    // 2. Try Text Matching (Case-insensitive)
                    const texts = ['accept all', 'accept all cookies', 'accept cookies', 'i accept', 'i agree', 'yes, i’m happy', 'allow all', 'aceitar todos', 'permitir todos', 'aceitar e fechar', 'concordo'];
                    const elements = [...document.querySelectorAll("button, div[role='button']")];
                    for (const el of elements) {
                        const inner = el.innerText.trim().toLowerCase();
                        if (texts.includes(inner)) {
                            el.click(); return true;
                        }
                    }
                    return false;
                }
                """
                
                # Poll up to 10 times (10 seconds)
                for attempt in range(10):
                    if banner_clicked: break
                    
                    # Run the JS natively inside every available frame
                    for frame in page.frames:
                        try:
                            # .evaluate() is instant and will not hang the Python thread
                            if frame.evaluate(js_clicker):
                                print(f"    [+] CMP Banner Clicked in frame: {frame.name}")
                                banner_clicked = True
                                break
                        except:
                            pass # Safely ignore cross-origin access errors
                            
                    if not banner_clicked:
                        page.wait_for_timeout(1000)

                if banner_clicked:
                    page.wait_for_timeout(3000) # Wait for cookies to drop
                else:
                    print("    [-] No banner found/clickable.")

            except Exception as e:
                print(f"    [-] Banner clicker encountered an error: {e}")
            # ==========================================
            # ==========================================

            # 3. Simulate human behavior to defeat Automation Bias
            page.mouse.move(500, 200, steps=10)
            page.wait_for_timeout(500)
            page.mouse.wheel(0, 600)  
            page.wait_for_timeout(500)
            page.mouse.move(600, 400, steps=10)

            # 4. Wait 15 seconds for Prebid.js and Ad Exchanges to bid!
            page.wait_for_timeout(15000)
            
        except Exception as e:
            print(f"[Error] Failed during execution of {site}: {e}")
            
        finally:
            # 5. Stop logging (Out-of-Band Python Request)
            # This completely bypasses the browser, eliminating WebKit freezes and CORS errors.
            try:
                # Configure Python to route its request through our mitmproxy
                proxy_support = urllib.request.ProxyHandler({'http': 'http://127.0.0.1:38080'})
                opener = urllib.request.build_opener(proxy_support)
                
                # Send the stop command directly to the proxy
                opener.open("http://240.240.240.240/stop", timeout=5)
                time.sleep(1.5) # Brief pause for proxy to commit SQLite transaction
                print("    [+] Proxy logging stopped cleanly.")
            except Exception as e:
                print(f"    [-] Proxy stop signal failed: {e}")

def main():
    parser = argparse.ArgumentParser(description="ETR Causal Inference Orchestrator")
    parser.add_argument("--browser", choices=["chrome", "brave", "firefox", "webkit"], required=True)
    parser.add_argument("--binary", help="Path to native browser executable (Chrome/Brave/Firefox)", default="")
    parser.add_argument("--hardened", action="store_true", help="Enable Firefox RFP or Brave Strict")
    args = parser.parse_args()

    # Define your domains for the Causal Workflow
    # Seeder sites: High commercial intent to build the persona profile
    SEEDER_SITES =[
        "https://www.bmw.com",
        "https://www.rolex.com",
        "https://www.redfin.com"
    ]
    
    # Publisher sites: Ad-heavy sites where we measure the RTB auctions (CPMs)
    PUBLISHER_SITES =[
        "https://www.cnn.com",
        "https://www.theguardian.com",
        "https://www.independent.co.uk"
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
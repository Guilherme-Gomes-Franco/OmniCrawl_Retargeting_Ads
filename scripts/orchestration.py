#!/usr/bin/env python3
import time
import socket
import threading
from playwright.sync_api import sync_playwright
import argparse
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
def create_browser_context(p, browser_type, binary_path):
    """Launches native browser binaries with Playwright and forces Stealth."""
    print(f"\n[Orchestrator] Launching {browser_type} context...")
    
    # Standard Windows 10 Chrome User-Agent to blend in
    SPOOFED_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    
    if browser_type in ["chrome", "brave"]:
        context = p.chromium.launch_persistent_context(
            user_data_dir="", 
            executable_path=binary_path,
            headless=False,
            proxy={"server": "http://127.0.0.1:38080"},
            user_agent=SPOOFED_UA,
            viewport={"width": 1920, "height": 1080},
            ignore_default_args=[
                "--enable-automation", 
                "--no-sandbox", 
                "--disable-setuid-sandbox"
            ],
            args=[
                "--disable-blink-features=AutomationControlled", 
                "--test-type", # Suppresses "Unsupported command-line flag" banners
                "--no-default-browser-check",
                "--disable-search-engine-choice-screen"
            ]
        )
    elif browser_type == "firefox":
        # Force Firefox to trust the Fedora OS certificates (mitmproxy)
        user_js_path = os.path.join(profile_path, 'user.js') if profile_path else "user.js"
        with open(user_js_path, 'a') as f:
            f.write('\nuser_pref("dom.webdriver.enabled", false);\n')
            f.write('user_pref("useAutomationExtension", false);\n')
            f.write('user_pref("security.enterprise_roots.enabled", true);\n') 

        context = p.firefox.launch_persistent_context(
            user_data_dir=profile_path,
            executable_path=binary_path,
            headless=False,
            proxy={"server": "http://127.0.0.1:38080"},
            viewport={"width": 1920, "height": 1080},
            ignore_default_args=["--enable-automation"]
        )
    elif browser_type == "webkit":
        context = p.webkit.launch_persistent_context(
            user_data_dir="",
            headless=False,
            proxy={"server": "http://127.0.0.1:38080"},
            viewport={"width": 1920, "height": 1080},
            ignore_default_args=["--enable-automation"]
        )
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
            # 2.5 AUTO-ACCEPT COOKIES (To unblock ad auctions hidden behind CMPs)
            # ==========================================
            print("    [+] Hunting for CMP banners (polling for up to 10 seconds)...")
            try:
                accept_texts =[
                    'Accept All', 'Accept all', 'Accept All Cookies', 'Accept cookies', 'Accept',
                    'I Accept', 'Yes, I’m happy', 'Allow All', 'Allow all',
                    'Aceitar todos', 'Permitir todos', 'Aceitar e fechar'
                ]
                
                banner_clicked = False
                
                # Poll for up to 10 seconds to allow slow CMP scripts to load
                for attempt in range(10):
                    if banner_clicked:
                        break
                        
                    for frame in page.frames:
                        if banner_clicked:
                            break
                        
                        # 1. Check known CMP CSS IDs/Classes (Zero false positives)
                        try:
                            # ADDED: button#accept-btn and .qc-cmp2-summary-buttons button[mode="primary"] for custom Quantcast
                            cmp_selectors = (
                                "#onetrust-accept-btn-handler, button.sp_choice_type_11, "
                                ".didomi-continue-button, .qc-cmp2-b-agree, #uc-btn-accept-banner, "
                                "button#accept-btn, .qc-cmp2-summary-buttons button[mode='primary']"
                            )
                            cmp_btn = frame.locator(cmp_selectors).first
                            
                            if cmp_btn.is_visible():
                                cmp_btn.click(force=True)
                                print(f"    [+] Clicked known CMP banner via CSS in frame: {frame.name}")
                                banner_clicked = True
                                break
                        except:
                            pass
                            
                        # 2. Check Strict Text Matches (Multi-word only)
                        if not banner_clicked:
                            # ADDED: 'I agree', 'I Agree', and 'Concordo'
                            accept_texts =[
                                'Accept All', 'Accept all', 'Accept All Cookies', 'Accept cookies', 
                                'I Accept', 'I agree', 'I Agree', 'Yes, I’m happy', 'Allow All', 'Allow all',
                                'Aceitar todos', 'Permitir todos', 'Aceitar e fechar', 'Concordo'
                            ]
                            
                            for text in accept_texts:
                                try:
                                    txt_btn = frame.locator(f"button:has-text('{text}'), div[role='button']:has-text('{text}')").first
                                    if txt_btn.is_visible():
                                        txt_btn.click(force=True)
                                        print(f"    [+] Clicked banner using strict text '{text}' in frame: {frame.name}")
                                        banner_clicked = True
                                        break
                                except:
                                    pass

                    if not banner_clicked:
                        # Wait 1 second before scanning the DOM/Frames again
                        page.wait_for_timeout(1000) 

                if banner_clicked:
                    # Give the page 3 seconds to drop the cookies and fire the Prebid.js tags
                    page.wait_for_timeout(3000)
                else:
                    print("    [-] No banner found after 10 seconds.")
                    
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
            # 5. Stop logging using a background API call (doesn't disrupt the page)
            try:
                page.goto("http://240.240.240.240/stop", wait_until="commit", timeout=5000)
                time.sleep(1) # Brief pause for proxy to commit SQLite transaction
            except Exception:
                pass

def main():
    parser = argparse.ArgumentParser(description="ETR Causal Inference Orchestrator")
    parser.add_argument("--browser", choices=["chrome", "brave", "firefox", "webkit"], required=True)
    parser.add_argument("--binary", help="Path to native browser executable (Chrome/Brave/Firefox)", default="")
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
            context = create_browser_context(p, args.browser, args.binary)
            
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
            context = create_browser_context(p, args.browser, args.binary)
            
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
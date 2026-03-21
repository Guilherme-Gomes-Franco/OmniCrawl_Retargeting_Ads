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
    
    if browser_type in["chrome", "brave"]:
        context = p.chromium.launch_persistent_context(
            user_data_dir="", # Ephemeral dir for strict state control
            executable_path=binary_path,
            headless=False,
            proxy={"server": "http://127.0.0.1:38080"},
            ignore_default_args=["--enable-automation"],
            args=["--disable-blink-features=AutomationControlled", "--ignore-certificate-errors"]
        )
    elif browser_type == "firefox":
        context = p.firefox.launch_persistent_context(
            user_data_dir="",
            executable_path=binary_path,
            headless=False,
            proxy={"server": "http://127.0.0.1:38080"},
            ignore_default_args=["--enable-automation"]
        )
    elif browser_type == "webkit":
        context = p.webkit.launch_persistent_context(
            user_data_dir="",
            headless=False,
            proxy={"server": "http://127.0.0.1:38080"},
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
        
        # 1. Tell mitmproxy to start logging for this specific URL
        start_api = f"http://240.240.240.240/start?url={site}&browser={browser_id}_{phase_name}&sync_host=127.0.0.1&sync_port={sync_port}&scroll=true"
        
        try:
            # The proxy intercepts this and auto-redirects to the target 'site'
            page.goto(start_api, wait_until="networkidle", timeout=60000)
            
            # 2. Wait 15 seconds. This is CRITICAL to allow Prebid.js, RTB auctions, 
            # and Cookie Sync (CSync) network meshes to fully execute.
            page.wait_for_timeout(15000)
            
        except Exception as e:
            print(f"[Error] Failed to load {site}: {e}")
            
        finally:
            # 3. Tell mitmproxy to stop logging and commit to DB
            try:
                page.goto("http://240.240.240.240/stop", timeout=10000)
                time.sleep(1) # Brief pause to allow the TCP SYN/ACK handshake to finish
            except:
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
        "https://www.zillow.com"
    ]
    
    # Publisher sites: Ad-heavy sites where we measure the RTB auctions (CPMs)
    PUBLISHER_SITES =[
        "https://www.cnn.com",
        "https://www.weather.com",
        "https://www.forbes.com"
    ]

    sync_port = 50505
    sync_server = CrawlerSyncServer(port=sync_port)
    sync_server.start()

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

    sync_server.stop()
    print("\n[Orchestrator] Causal Inference crawl complete! Logs saved to OmniCrawl database.")

if __name__ == "__main__":
    main()
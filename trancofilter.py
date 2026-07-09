import requests
import csv
import time
import re

# 1. ALLOWED TLDs
ENGLISH_TLDS = ('.com', '.net', '.org', '.uk', '.ca', '.au', '.nz', '.ie')

# 2. HARDENED BLACKLIST (Removing Platforms/Utilities that don't use Open RTB)
BLACKLIST = [
    "google", "facebook", "fbcdn", "amazon", "apple", "microsoft", "netflix", 
    "twitter", "x.com", "instagram", "linkedin", "tiktok", "wikipedia", "github",
    "stackoverflow", "wordpress", "adobe", "spotify", "zoom", "gov", "edu",
    "bing", "vimeo", "youtube", "roblox", "flickr", "soundcloud", "opera",
    "atlassian", "yandex", "vk.com", "userapi", "myfritz", "wp.com", "cloudns",
    "speedtest", "researchgate", "sourceforge", "archive.org", "ebay", "paypal"
]

def has_transparent_auctions(domain):
    """
    Checks the site's HTML for Prebid.js or other Header Bidding wrappers.
    This ensures we only visit sites where we can actually READ the CPM.
    """
    try:
        # We need a real User-Agent to see the full scripts
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(f"https://www.{domain}", timeout=6, headers=headers)
        html = response.text.lower()
        
        # Look for Prebid.js indicators (the global pbjs object or the script itself)
        indicators = [
            'prebid.js', 
            'pbjs.que', 
            'pubfood', 
            'amazon-adsystem', # Amazon Transparent Ad Marketplace
            'apstag.js',
            'gpt.js' # Google Tag - usually present alongside Header Bidding
        ]
        
        if any(ind in html for ind in indicators):
            return True
    except:
        pass
    return False

def is_publisher(domain):
    """Verifies ads.txt existence."""
    try:
        url = f"https://{domain}/ads.txt"
        response = requests.get(url, timeout=3)
        if response.status_code == 200 and "DIRECT" in response.text.upper():
            return True
    except:
        pass
    return False

def filter_tranco_transparent_publishers(input_file, output_file, limit=100):
    publishers = []
    print(f"[*] Filtering for TRANSPARENT Publishers (Prebid/Header Bidding)...")
    
    with open(input_file, 'r') as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if len(publishers) >= limit:
                break
            
            domain = row[1].lower()

            # Step 1: Check TLD
            if not domain.endswith(ENGLISH_TLDS):
                continue

            # Step 2: Blacklist Check
            if any(junk in domain for junk in BLACKLIST):
                continue

            # Step 3: Check for Transparent Header Bidding (The most important step!)
            print(f"[?] Verifying Tech Stack: {domain}...")
            if has_transparent_auctions(domain):
                # Step 4: ads.txt Check
                if is_publisher(domain):
                    print(f"    [+] Found Quality Publisher: {domain}")
                    publishers.append(f"https://www.{domain}")
                
                time.sleep(0.1) # Polite delay

    # Save output
    with open(output_file, 'w') as f:
        f.write("PUBLISHER_SITES = [\n")
        for pub in publishers:
            f.write(f'    "{pub}",\n')
        f.write("]\n")
    
    print(f"\n[!] Success! Found {len(publishers)} sites with transparent auction potential.")

if __name__ == "__main__":
    filter_tranco_transparent_publishers("tranco_list.csv", "publishers_v2.py", limit=150)
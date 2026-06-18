import requests
import csv
import time

# 1. ALLOWED TLDs (High probability of English content)
ENGLISH_TLDS = ('.com', '.net', '.org', '.uk', '.ca', '.au', '.nz', '.ie')

# 2. EXCLUSION LIST (Non-Ad sites)
BLACKLIST = [
    "google", "facebook", "amazon", "apple", "microsoft", "netflix", 
    "twitter", "instagram", "linkedin", "tiktok", "wikipedia", "github",
    "stackoverflow", "wordpress", "adobe", "spotify", "zoom", "gov", "edu"
]

def is_english_content(domain):
    """Checks if the site's HTML declares it is in English."""
    try:
        # We only need the headers and the very start of the HTML to find the lang tag
        response = requests.get(f"https://{domain}", timeout=4, headers={'Accept-Language': 'en-US,en;q=0.5'})
        
        # Method 1: Check HTTP Headers
        content_lang = response.headers.get('Content-Language', '').lower()
        if 'en' in content_lang:
            return True
            
        # Method 2: Check for <html lang="en"> in the first 5000 characters
        html_start = response.text[:5000].lower()
        if 'lang="en"' in html_start or "lang='en'" in html_start or 'lang=en' in html_start:
            return True
    except:
        pass
    return False

def is_publisher(domain):
    """Verifies the site participates in RTB via ads.txt."""
    try:
        url = f"https://{domain}/ads.txt"
        response = requests.get(url, timeout=3)
        if response.status_code == 200 and "DIRECT" in response.text.upper():
            return True
    except:
        pass
    return False

def filter_tranco_english(input_file, output_file, limit=100):
    publishers = []
    print(f"[*] Filtering Tranco list for English Publishers...")
    
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

            # Step 3: English Language Check
            print(f"[?] Checking Language: {domain}...")
            if is_english_content(domain):
                # Step 4: ads.txt Check (Confirm it's a publisher selling ads)
                if is_publisher(domain):
                    print(f"    [+] Found English Publisher: {domain}")
                    publishers.append(f"https://www.{domain}")
                
                time.sleep(0.05) # Polite delay

    # Save output
    with open(output_file, 'w') as f:
        f.write("PUBLISHER_SITES = [\n")
        for pub in publishers:
            f.write(f'    "{pub}",\n')
        f.write("]\n")
    
    print(f"\n[!] Done! Saved {len(publishers)} English publishers to {output_file}")

if __name__ == "__main__":
    # Ensure you have tranco_list.csv in the same folder
    filter_tranco_english("tranco_list.csv", "publishers_english.py", limit=100)
import requests
import csv
import time

# 1. EXCLUSION LIST (Utility/Social/Non-Ad Sites)
# These are popular but useless for RTB measurement.
BLACKLIST = [
    "google", "facebook", "amazon", "apple", "microsoft", "netflix", 
    "twitter", "instagram", "linkedin", "tiktok", "cloudflare", "akamai",
    "github", "stackoverflow", "wordpress", "pinterest", "adobe", "spotify",
    "zoom", "aws", "cdn", "api", "static", "googlevideo", "ytimg"
]

# 2. INCLUSION KEYWORDS (Heuristic for Media/News)
# Sites with these words in the domain are high-probability publishers.
MEDIA_KEYWORDS = [
    "news", "times", "daily", "post", "journal", "gazette", "mirror", 
    "herald", "tribune", "independent", "magazine", "blog", "tech", 
    "review", "standard", "chronicle", "world", "today"
]

def is_publisher(domain):
    """Checks if a domain has an ads.txt file (the gold standard for publishers)."""
    try:
        url = f"https://{domain}/ads.txt"
        # We use a short timeout so we don't hang on dead sites
        response = requests.get(url, timeout=3, allow_redirects=True)
        # If ads.txt exists and is large enough, it's a real publisher
        if response.status_code == 200 and "DIRECT" in response.text:
            return True
    except:
        pass
    return False

def filter_tranco(input_file, output_file, limit):
    publishers = []
    print(f"[*] Reading {input_file}...")
    
    with open(input_file, 'r') as f:
        # Assumes Tranco CSV format: "Rank,Domain"
        reader = csv.reader(f)
        for row in reader:
            if len(publishers) >= limit:
                break
            
            domain = row[1].lower()

            # Immediately skip any domain that doesn't end with .com
            if not domain.endswith(".com"):
                continue
            
            # Step A: Heuristic Check (Fast)
            if any(junk in domain for junk in BLACKLIST):
                continue
                
            # Step B: Keyword Check (Prioritize Media)
            is_potential = any(kw in domain for kw in MEDIA_KEYWORDS)
            
            if is_potential:
                print(f"[?] Verifying {domain} via ads.txt...")
                # Step C: Deep Verification (Slow but Scientific)
                if is_publisher(domain):
                    print(f"    [+] Found Publisher: {domain}")
                    publishers.append(f"https://www.{domain}")
                
                # Small sleep to be polite to the servers
                time.sleep(0.1)

    # Save to your orchestration format
    with open(output_file, 'w') as f:
        f.write("PUBLISHER_SITES = [\n")
        for pub in publishers:
            f.write(f'    "{pub}",\n')
        f.write("]\n")
    
    print(f"\n[!] Success! Saved {len(publishers)} publishers to {output_file}")

if __name__ == "__main__":
    # Point this to your Tranco CSV file
    filter_tranco("tranco_list.csv", "publishers.py", limit=150)
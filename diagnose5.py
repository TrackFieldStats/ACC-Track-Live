import sys, requests
from bs4 import BeautifulSoup
sys.path.insert(0, '.')

BASE = "https://flashresults.com/2026_Meets/Indoor/02-26_ACC"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

from scraper import _parse_result_page

url = f"{BASE}/001-1_start.htm"
resp = requests.get(url, headers=HEADERS, timeout=15)
soup = BeautifulSoup(resp.text, "html.parser")

athletes, status = _parse_result_page(soup, is_start_list=True)
print(f"Status: {status}  Athletes found: {len(athletes)}")
for a in athletes:
    print(f"  name='{a.name}' team='{a.team}' seed='{a.seed_mark}'")

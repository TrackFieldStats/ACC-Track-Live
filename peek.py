import requests
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:148.0) Gecko/20100101 Firefox/148.0",
    "Accept": "text/html, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Connection": "keep-alive",
    "Referer": "https://flashresults.com/2026_Meets/Indoor/02-26_ACC/index.htm",
}
resp = requests.get(
    "https://flashresults.com/2026_Meets/Indoor/02-26_ACC/007-1_compiled.htm",
    headers=HEADERS, timeout=15
)
print(resp.status_code)
print(resp.text[:500])
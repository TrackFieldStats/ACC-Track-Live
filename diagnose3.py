"""
diagnose3.py - Check what the index parser sees for event names and genders.
Run with: python diagnose3.py
"""
import sys, requests
from bs4 import BeautifulSoup
sys.path.insert(0, '.')

BASE = "https://flashresults.com/2026_Meets/Indoor/02-26_ACC"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def check_index():
    from scraper import parse_index, _infer_gender

    print("=== RAW INDEX PARSE ===")
    raw_events, meet_name = parse_index(BASE)
    print(f"Meet name: {meet_name}")
    print(f"Total raw events found: {len(raw_events)}")
    print()
    print(f"{'Event Name':40s} {'Gender':8s} {'Round':10s} {'URL snippet'}")
    print("-"*80)
    for e in raw_events:
        gender = _infer_gender(e['event_name'])
        print(f"  {e['event_name']:40s} {gender.value:8s} {e['round_str']:10s} {e['compiled_href']}")

if __name__ == "__main__":
    check_index()
    print("\nPaste this output back to Claude.")

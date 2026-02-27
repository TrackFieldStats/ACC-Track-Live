"""
diagnose2.py - Targeted diagnostic for Women's scoring bug.
Run with: python diagnose2.py
"""
import sys, requests
from bs4 import BeautifulSoup
sys.path.insert(0, '.')

BASE = "https://flashresults.com/2026_Meets/Indoor/02-26_ACC"

def check_womens_events():
    from scraper import scrape_meet
    from data_model import Gender, EventStatus, RoundType

    print("Scraping meet (takes ~2 min)...")
    state = scrape_meet(BASE)

    print("\n=== ALL WOMEN'S EVENTS: status and round type ===")
    womens = [e for e in state.events if e.gender == Gender.WOMEN]
    print(f"Total women's events found: {len(womens)}")
    print()

    finals_complete = 0
    for e in womens:
        entries_with_places = [en for en in e.entries if en.athlete.final_place is not None]
        print(f"  {e.event_name:35s} round={e.round_type.value:8s} status={e.status.value:12s} entries={len(e.entries)} placed={len(entries_with_places)}")
        if e.round_type == RoundType.FINAL and e.status == EventStatus.FINAL:
            finals_complete += 1

    print(f"\nWomen's completed finals: {finals_complete}")

    # Also show the first women's final event entries in detail
    first_final = next((e for e in womens if e.round_type == RoundType.FINAL and e.status == EventStatus.FINAL), None)
    if first_final:
        print(f"\n=== Sample final: {first_final.event_name} ===")
        for entry in first_final.entries[:5]:
            a = entry.athlete
            print(f"  place={a.final_place} name='{a.name}' team='{a.team}' mark='{a.final_mark}'")
    else:
        print("\nNo women's completed finals found at all!")
        # Show what round_types exist
        round_types = set(e.round_type for e in womens)
        statuses = set(e.status for e in womens)
        print(f"Round types present: {round_types}")
        print(f"Statuses present: {statuses}")

if __name__ == "__main__":
    check_womens_events()
    print("\nPaste this output back to Claude.")

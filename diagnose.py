"""
diagnose.py - Full diagnostic. Run with: python diagnose.py
"""
import re, sys, requests
from bs4 import BeautifulSoup
sys.path.insert(0, '.')

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
BASE = "https://flashresults.com/2026_Meets/Indoor/02-26_ACC"

def test_splitter():
    print("\n=== TEST 1: Name/Team Splitter ===")
    from scraper import _split_athlete_team
    tests = [
        ("Jordan ANTHONYArkansas [JR]", "Jordan ANTHONY", "Arkansas"),
        ("Israel OKONAuburn [FR]",       "Israel OKON",    "Auburn"),
        ("Brianna LYSTONLSU [JR]",       "Brianna LYSTON", "LSU"),
        ("Kaila JACKSONGeorgia [JR]",    "Kaila JACKSON",  "Georgia"),
        ("Layla ANDERSONTennessee [SR]", "Layla ANDERSON", "Tennessee"),
    ]
    all_ok = True
    for raw, exp_name, exp_team in tests:
        name, team = _split_athlete_team(raw)
        ok = name == exp_name and team == exp_team
        if not ok: all_ok = False
        print(f"  {'OK' if ok else 'FAIL'}  name='{name}' team='{team}'" + (f"  expected='{exp_name}'/'{exp_team}'" if not ok else ""))
    print(f"  Result: {'PASS' if all_ok else 'FAIL'}")
    return all_ok

def test_parser():
    print("\n=== TEST 2: Parser - Men 60m Final ===")
    from scraper import _parse_result_page
    url = f"{BASE}/021-2_compiled.htm"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(resp.text, "html.parser")
    athletes, status = _parse_result_page(soup, is_start_list=False)
    print(f"  Status: {status}  Athletes: {len(athletes)}")
    for a in athletes:
        print(f"    Place {a.final_place}: '{a.name}' | '{a.team}' | {a.final_mark}")
    ok = len(athletes) >= 8 and any(a.team == "Arkansas" for a in athletes)
    print(f"  Result: {'PASS' if ok else 'FAIL'}")
    return ok

def test_full_scrape():
    print("\n=== TEST 3: Full Scrape + Scoring (takes ~2 min) ===")
    from scraper import scrape_meet
    from scoring import run_all_analysis
    from data_model import Gender
    state = scrape_meet(BASE)
    women = run_all_analysis(state, Gender.WOMEN)
    men   = run_all_analysis(state, Gender.MEN)
    print("  WOMEN TOP 5:")
    for ts in women["team_scores"][:5]:
        print(f"    {ts.team:20s} actual={ts.actual_points} proj={ts.seed_projection} win={ts.win_probability:.1f}%")
    print("  MEN TOP 5:")
    for ts in men["team_scores"][:5]:
        print(f"    {ts.team:20s} actual={ts.actual_points} proj={ts.seed_projection} win={ts.win_probability:.1f}%")
    ok = any(ts.actual_points > 0 for ts in women["team_scores"])
    print(f"  Result: {'PASS' if ok else 'FAIL - scores still zero'}")
    return ok

if __name__ == "__main__":
    t1 = test_splitter()
    t2 = test_parser() if t1 else False
    t3 = test_full_scrape() if t2 else False
    print(f"\nSUMMARY: Splitter={'PASS' if t1 else 'FAIL'} Parser={'PASS' if t2 else 'FAIL'} FullScrape={'PASS' if t3 else 'FAIL/SKIPPED'}")
    print("Paste this output back to Claude if anything failed.")

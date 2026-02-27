import sys
sys.path.insert(0, '.')

BASE = "https://flashresults.com/2026_Meets/Indoor/02-26_ACC"

def check():
    from scraper import scrape_meet
    from scoring import compute_actual_scores
    from config import PLACE_POINTS
    from data_model import Gender, EventStatus, RoundType

    print("Scraping (takes ~2 min)...")
    state = scrape_meet(BASE)

    print(f"\nCombined events found: {len(state.combined_events)}")
    for ce in state.combined_events:
        print(f"  {ce.event_name} | gender={ce.gender.value} | complete={ce.is_complete} | athletes={len(ce.athletes)}")
        for a in ce.athletes[:3]:
            print(f"    place={a.final_place} name='{a.name}' team='{a.team}'")

    women_scores = compute_actual_scores(state, Gender.WOMEN)
    men_scores = compute_actual_scores(state, Gender.MEN)

    official_w = {
        "Notre Dame": 25, "Miami": 24, "Virginia": 23, "Duke": 18,
        "Boston College": 16, "Wake Forest": 15, "NC State": 8,
        "North Carolina": 6, "SMU": 5, "Stanford": 5,
        "California": 3, "Clemson": 3, "Louisville": 2,
        "Virginia Tech": 2, "Florida State": 1,
        "Georgia Tech": 0, "Pittsburgh": 0, "Syracuse": 0,
    }
    official_m = {
        "Virginia": 45, "Louisville": 23, "North Carolina": 22.5,
        "Clemson": 22, "Notre Dame": 19, "Wake Forest": 13,
        "Duke": 11, "Miami": 10, "Virginia Tech": 7,
        "California": 7, "Stanford": 6, "Boston College": 5,
        "NC State": 4.5, "Florida State": 0, "Georgia Tech": 0,
        "Pittsburgh": 0, "Syracuse": 0,
    }

    print("\n=== WOMEN'S SCORES ===")
    all_teams = set(official_w) | set(women_scores)
    for team in sorted(all_teams, key=lambda t: -official_w.get(t,0)):
        calc = women_scores[team].actual_points if team in women_scores else 0
        off = official_w.get(team, 0)
        diff = calc - off
        flag = " OK" if abs(diff) < 0.2 else f" OFF by {diff:+.2f}"
        print(f"  {team:20s} official={off:6.2f} calc={calc:6.2f}{flag}")

    print("\n=== MEN'S SCORES ===")
    all_teams = set(official_m) | set(men_scores)
    for team in sorted(all_teams, key=lambda t: -official_m.get(t,0)):
        calc = men_scores[team].actual_points if team in men_scores else 0
        off = official_m.get(team, 0)
        diff = calc - off
        flag = " OK" if abs(diff) < 0.2 else f" OFF by {diff:+.2f}"
        print(f"  {team:20s} official={off:6.2f} calc={calc:6.2f}{flag}")

if __name__ == "__main__":
    check()
    print("\nPaste output back to Claude if any are OFF.")

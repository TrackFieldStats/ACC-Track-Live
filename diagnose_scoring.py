"""
diagnose_scoring.py - Shows exactly what events are being scored,
what athletes/teams are parsed from each, and what points are assigned.

Run with: python diagnose_scoring.py
"""
import sys
sys.path.insert(0, '.')

from scraper import scrape_meet
from scoring import compute_actual_scores, compute_win_probability, compute_leverage_index
from data_model import Gender, EventStatus, RoundType
from config import PLACE_POINTS

BASE = "https://flashresults.com/2026_Meets/Indoor/02-26_ACC"

CORRECT_WOMEN = {
    "Notre Dame": 25, "Miami": 24, "Virginia": 23, "Duke": 18,
    "Boston College": 16, "Wake Forest": 15, "NC State": 8,
    "North Carolina": 6, "SMU": 5, "Stanford": 5,
    "California": 3, "Clemson": 3, "Louisville": 2,
    "Virginia Tech": 2, "Florida State": 1,
    "Georgia Tech": 0, "Pittsburgh": 0, "Syracuse": 0,
}
CORRECT_MEN = {
    "Virginia": 45, "Louisville": 23, "North Carolina": 22.5,
    "Clemson": 22, "Notre Dame": 19, "Wake Forest": 13,
    "Duke": 11, "Miami": 10, "Virginia Tech": 7,
    "California": 7, "Stanford": 6, "Boston College": 5,
    "NC State": 4.5, "Florida State": 0, "Georgia Tech": 0,
    "Pittsburgh": 0, "Syracuse": 0,
}

def print_section(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print('='*70)

def diagnose_gender(state, gender, correct):
    label = gender.value.upper()
    print_section(f"{label} — COMPLETED FINALS (events marked as FINAL)")

    completed = [e for e in state.events
                 if e.gender == gender
                 and e.round_type == RoundType.FINAL
                 and e.status == EventStatus.FINAL]

    for e in completed:
        placed = [(en.athlete.final_place, en.athlete.name, en.athlete.team, en.athlete.final_mark)
                  for en in e.entries if en.athlete.final_place is not None]
        placed.sort(key=lambda x: x[0])
        print(f"\n  EVENT: {e.event_name}")
        print(f"  URL:   {e.compiled_url}")
        print(f"  Total entries parsed: {len(e.entries)}")
        if placed:
            for pl, name, team, mark in placed[:10]:
                pts = PLACE_POINTS.get(pl, 0)
                print(f"    {pl}. {name:<30s} {team:<20s} {mark:<10s} → {pts} pts")
        else:
            print(f"    ⚠️  NO PLACED ATHLETES — places not parsed!")
            print(f"    First 5 entries:")
            for en in e.entries[:5]:
                a = en.athlete
                print(f"      name='{a.name}' team='{a.team}' mark='{a.final_mark}' place={a.final_place}")

    print_section(f"{label} — COMBINED EVENTS STATUS")
    for ce in state.combined_events:
        if ce.gender != gender:
            continue
        print(f"\n  {ce.event_name}: complete={ce.is_complete} athletes={len(ce.athletes)}")

        # Check final sub-event gate
        event_name_lower = ce.event_name.lower()
        if "pentathlon" in event_name_lower:
            final_sub = "800m"
        elif "heptathlon" in event_name_lower:
            final_sub = "1000m"
        else:
            final_sub = None

        if final_sub:
            sub_events = [e for e in state.events
                          if final_sub in e.event_name.lower()
                          and ("pentathlon" in e.event_name.lower()
                               or "heptathlon" in e.event_name.lower())]
            if sub_events:
                for se in sub_events:
                    print(f"    Final sub-event '{se.event_name}': status={se.status.value}")
            else:
                print(f"    ⚠️  Final sub-event '{final_sub}' NOT FOUND in state.events")

        if ce.athletes:
            print(f"    Top 5 athletes:")
            for a in ce.athletes[:5]:
                print(f"      place={a.final_place} {a.name:<30s} {a.team}")

    print_section(f"{label} — SCORE COMPARISON")
    scores = compute_actual_scores(state, gender)

    all_teams = sorted(set(list(correct.keys()) + list(scores.keys())))
    errors = []
    for team in all_teams:
        calc = scores[team].actual_points if team in scores else 0
        exp = correct.get(team, 0)
        diff = calc - exp
        flag = "✅" if abs(diff) < 0.1 else f"❌ {'OVER' if diff > 0 else 'UNDER'} by {abs(diff):.1f}"
        print(f"  {team:<22s} expected={exp:6.1f}  calc={calc:6.1f}  {flag}")
        if abs(diff) >= 0.1:
            errors.append((team, exp, calc, diff))

    if errors:
        print(f"\n  {label} ERRORS ({len(errors)} teams off):")
        for team, exp, calc, diff in errors:
            ts = scores.get(team)
            if ts and ts.events_scored:
                print(f"\n    {team} (expected {exp}, got {calc}):")
                for ev in ts.events_scored:
                    print(f"      scored: {ev}")
    else:
        print(f"\n  ✅ All {label} scores match!")

    print_section(f"{label} — VIRGINIA EVENT DETAIL (debugging)")
    if gender == Gender.WOMEN:
        target_team = "Notre Dame"
    else:
        target_team = "Virginia"
    for e in state.events:
        if e.gender != gender:
            continue
        team_entries = [en for en in e.entries if en.athlete.team == target_team]
        if team_entries:
            print(f"\n  {e.event_name} (status={e.status.value}, round={e.round_type.value}):")
            for en in team_entries:
                a = en.athlete
                print(f"    {a.name:<30s} place={a.final_place}  mark='{a.final_mark}'  seed='{a.seed_mark}'")


    relay_events = [e for e in state.events
                    if e.gender == gender and "relay" in e.event_name.lower()
                    and e.status == EventStatus.FINAL]
    if not relay_events:
        print("  No completed relay finals yet.")
    for e in relay_events:
        print(f"\n  {e.event_name}:")
        for en in e.entries:
            print(f"    name='{en.athlete.name}'  team='{en.athlete.team}'  place={en.athlete.final_place}")

    print_section(f"{label} — EVENTS NOT BEING SCORED (SCHEDULED/IN_PROGRESS finals)")
    not_scored = [e for e in state.events
                  if e.gender == gender
                  and e.round_type == RoundType.FINAL
                  and e.status != EventStatus.FINAL]
    for e in not_scored:
        print(f"  {e.event_name:<40s} status={e.status.value}  entries={len(e.entries)}")
        if e.entries:
            print(f"    Sample entry: name='{e.entries[0].athlete.name}' mark='{e.entries[0].athlete.final_mark}' place={e.entries[0].athlete.final_place}")

    print_section(f"{label} — LEVERAGE INDEX DIAGNOSTIC")
    actual_scores = compute_actual_scores(state, gender)
    try:
        result = compute_win_probability(actual_scores, state, gender)
        if isinstance(result, tuple) and len(result) == 3:
            win_probs, top4_probs, _ = result
        else:
            win_probs, top4_probs = result
    except Exception as e:
        print(f"  ⚠️  compute_win_probability error: {e}")
        win_probs, top4_probs = {}, {}
    leverage = compute_leverage_index(state, gender, actual_scores, top4_probs)
    print(f"\n  Contenders (>15% top-4 probability):")
    for team, prob in sorted(top4_probs.items(), key=lambda x: x[1], reverse=True):
        if prob >= 0.15:
            print(f"    {team:<22s} {prob*100:.1f}%")
    print()
    print(f"  {'Event':<35s} {'Score':>7} {'Swing×C':>9} {'Run×W':>7} {'Pos':>4} {'Tag'}")
    print(f"  {'-'*35} {'-'*7} {'-'*9} {'-'*7} {'-'*4} {'-'*18}")
    for lev in leverage[:10]:
        d = lev.get('_debug', {})
        pos = str(d.get('clinch_position', '-'))
        print(f"  {lev['event_name']:<35s} "
              f"{lev['leverage_score']:>7.2f} "
              f"{d.get('swing_x_contest', 0):>9.2f} "
              f"{d.get('runaway_x_weight', 0):>7.2f} "
              f"{pos:>4}  "
              f"{lev['narrative']}")
    print(f"\n  RUNAWAY_WEIGHT=5. Contender threshold=15% top-4 probability.")


if __name__ == "__main__":
    print("Scraping meet (this takes ~2 minutes)...")
    state = scrape_meet(BASE)
    print(f"Scraped {len(state.events)} events, {len(state.combined_events)} combined events.")

    diagnose_gender(state, Gender.WOMEN, CORRECT_WOMEN)
    diagnose_gender(state, Gender.MEN, CORRECT_MEN)

    print("\n" + "="*70)
    print("  DONE — paste output back to Claude")
    print("="*70)

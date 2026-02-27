import sys
sys.path.insert(0, '.')
from scraper import scrape_meet
from scoring import (compute_actual_scores, compute_seed_projection,
                     compute_team_scenarios, _get_finalist_entries,
                     _seed_sort_key)
from data_model import Gender

state = scrape_meet('https://flashresults.com/2026_Meets/Indoor/02-26_ACC')
actual = compute_actual_scores(state, Gender.WOMEN)
proj = compute_seed_projection(actual, state, Gender.WOMEN)
scenario = compute_team_scenarios('Virginia', actual, state, Gender.WOMEN)

print(f"Projection total:      {proj.get('Virginia', 0):.1f}")
print(f"Scenario seeds-hold:   {scenario['scenario_a']:.1f}")
print(f"Scenario best-case:    {scenario['scenario_b']:.1f}")

print("\n=== EVENT BREAKDOWN (scenario) ===")
for ev in scenario['breakdown']:
    print(f"  {ev['event']:30s} seed_hold={ev['scenario_a_pts']:.1f}  best={ev['scenario_b_pts']:.1f}")
    for a in ev['athletes']:
        print(f"    {a['athlete']:30s} seed={a['seed_mark']:8s} proj_place={a['proj_place']}")

print("\n=== PROJECTION EVENT DETAIL FOR GEORGIA ===")
for event in state.get_upcoming_finals(Gender.WOMEN):
    finalist_entries = _get_finalist_entries(event, state, Gender.WOMEN)
    if not finalist_entries:
        continue
    georgia = [e for e in finalist_entries if e.athlete.team == 'Virginia']
    if not georgia:
        continue
    ranked = sorted(finalist_entries, key=lambda e: _seed_sort_key(e, event))
    rank_map = {e.athlete.name: i+1 for i, e in enumerate(ranked)}
    pts = sum(__import__('config').PLACE_POINTS.get(rank_map.get(e.athlete.name,9), 0) for e in georgia)
    print(f"  {event.event_name:30s} athletes={len(georgia)}  pts={pts:.1f}")
    for e in georgia:
        r = rank_map.get(e.athlete.name, 9)
        print(f"    {e.athlete.name:30s} seed={e.effective_seed}  rank={r}")

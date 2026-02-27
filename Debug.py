
import sys
sys.path.insert(0, '.')
from scraper import scrape_meet
from scoring import compute_actual_scores, compute_optimistic_ceiling, compute_seed_projection
from data_model import Gender

state = scrape_meet('https://flashresults.com/2026_Meets/Indoor/02-26_ACC')
actual = compute_actual_scores(state, Gender.WOMEN)
ceiling = compute_optimistic_ceiling(actual, state, Gender.WOMEN)
proj = compute_seed_projection(actual, state, Gender.WOMEN)

print('=== WOMEN PROJECTED (top 10) ===')
for team, pts in sorted(proj.items(), key=lambda x: -x[1])[:10]:
    print(f'  {team:20s} proj={pts:6.1f}  ceil={ceiling.get(team,0):6.1f}')

print()
print('=== UPCOMING FINALS with entry counts ===')
for e in state.get_upcoming_finals(Gender.WOMEN):
    entries = e.entries or []
    if not entries:
        for o in state.events:
            if o.gender == Gender.WOMEN and o.event_code == e.event_code and o.entries:
                entries = o.entries
                break
    teams = {}
    for en in entries:
        teams[en.athlete.team] = teams.get(en.athlete.team, 0) + 1
    print(f'  {e.event_name:30s} entries={len(entries):3d}  top teams: {dict(list(sorted(teams.items(), key=lambda x:-x[1]))[:4])}')

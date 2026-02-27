"""
scoring.py - All analytical layers:
  1. Current actual score
  2. Optimistic ceiling (mathematical elimination)
  3. Seed-based projection
  4. Leverage index
  5. Win probability via Monte Carlo
  6. Scenario builder (seeds hold / best case / worst case per team)
"""

import random
import logging
from collections import defaultdict
from typing import Optional

from data_model import (
    MeetState, MeetEvent, TeamScore, Gender, EventStatus, RoundType
)
from config import PLACE_POINTS, MONTE_CARLO_ITERATIONS
from scraper import _mark_to_seconds

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Seed ordering helpers
# ---------------------------------------------------------------------------

def _seed_sort_key(entry, event: MeetEvent) -> float:
    """
    Return a float for sorting entries by seed quality.
    Lower = better for track events (faster time).
    Higher = better for field events (longer/higher mark).
    Returns a large float so unseedable athletes go to the back.
    """
    mark = entry.effective_seed or ""
    val = _mark_to_seconds(mark)
    if val is None:
        return 1e9

    name = event.base_event_name.lower()
    # Field events stored as negative in _mark_to_seconds → bigger magnitude = better
    field_keywords = ["jump", "vault", "throw", "shot", "weight", "discus", "javelin", "hammer"]
    if any(k in name for k in field_keywords):
        return -val   # reverse: larger mark is better (less negative after flip)
    return val        # track: smaller time is better


def _rank_entries_by_seed(event: MeetEvent) -> list:
    """Return entries sorted best→worst by effective seed mark."""
    entries = [e for e in event.entries if e.athlete.name]
    return sorted(entries, key=lambda e: _seed_sort_key(e, event))


# ---------------------------------------------------------------------------
# 1. Current actual score
# ---------------------------------------------------------------------------

def compute_actual_scores(state: MeetState, gender: Gender) -> dict[str, TeamScore]:
    """Tally points from all completed finals only."""
    scores: dict[str, TeamScore] = {}

    def _get_or_create(team: str) -> TeamScore:
        if team not in scores:
            scores[team] = TeamScore(team=team, gender=gender)
        return scores[team]

    # Regular finals
    for event in state.get_completed_finals(gender):
        # Group athletes by final_place to detect ties
        from collections import defaultdict as _dd
        place_groups = _dd(list)
        for entry in event.entries:
            a = entry.athlete
            if a.final_place and a.final_place in PLACE_POINTS:
                place_groups[a.final_place].append(a)

        for place, athletes_at_place in place_groups.items():
            n = len(athletes_at_place)
            # Split points across tied places: e.g. 2 tied for 3rd get (6+5)/2=5.5 each
            total_pts = sum(PLACE_POINTS.get(place + i, 0) for i in range(n))
            split_pts = total_pts / n
            for a in athletes_at_place:
                ts = _get_or_create(a.team)
                ts.actual_points += split_pts
                ts.events_scored.append(f"{event.event_name} ({place}{'+' if n > 1 else ''}={split_pts:.2f}pt)")

    # Combined events (Pent/Hep) — scoring rules differ:
    # Pentathlon: one-day event, score as soon as _Scores.htm shows complete standings
    # Heptathlon: two-day event, only score after the final sub-event (1000m) has posted
    for combined in state.combined_events:
        if combined.gender != gender or not combined.is_complete:
            continue

        event_name_lower = combined.event_name.lower()

        if "heptathlon" in event_name_lower:
            # Trust is_complete — the scraper sets FINAL only when [SCORED] appears
            # in the scores page modal title, meaning all sub-events are done.
            if not combined.is_complete:
                continue

        # Pentathlon: trust is_complete — it's a one-day event
        for a in combined.athletes:
            if a.final_place and a.final_place in PLACE_POINTS:
                pts = PLACE_POINTS[a.final_place]
                ts = _get_or_create(a.team)
                ts.actual_points += pts
                ts.events_scored.append(f"{combined.event_name} ({a.final_place})")

    return scores


# ---------------------------------------------------------------------------
# Helper: get realistic finalist entries for an upcoming final
# ---------------------------------------------------------------------------

def _get_finalist_entries(event: MeetEvent, state: MeetState, gender: Gender,
                           n_finalists: int = 8) -> list:
    """
    Returns the entries to use for projection/ceiling/Monte Carlo for an upcoming final.

    Rules:
    - If the final already has entries (post-prelim), use them as-is.
    - If the final has no entries but a prelim exists, take only the top-N seeds
      from the prelim (default 8) — these are the projected finalists.
    - Field events have no prelims, so all entries are used directly.
    """
    entries = event.entries

    if not entries:
        # Look for a paired prelim
        for other in state.events:
            if (other.gender == gender
                    and other.event_code == event.event_code
                    and other.round_type == RoundType.PRELIM
                    and other.entries):
                entries = other.entries
                break

    if not entries:
        return []

    # If entries came from a prelim (more than n_finalists), trim to top seeds
    if len(entries) > n_finalists:
        ranked = sorted(
            entries,
            key=lambda e: _seed_sort_key(e, event)
        )
        entries = ranked[:n_finalists]

    return entries


# ---------------------------------------------------------------------------
# 2. Realistic ceiling
# ---------------------------------------------------------------------------

def compute_optimistic_ceiling(
    actual: dict[str, TeamScore],
    state: MeetState,
    gender: Gender
) -> dict[str, int]:
    """
    Realistic ceiling: actual points + best plausible score from remaining finals.

    Two-tier seed-position cap:
    - Seeds 1-8:  can finish as high as 1st (legitimate contenders)
    - Seeds 9-12: capped at 5th place max (4pts) — dark horse, could sneak points
    - Seeds 13+:  excluded entirely (not realistic scorers)

    Per-team optimistic within those constraints — does NOT deduct from other teams.
    """
    ceilings: dict[str, int] = defaultdict(int)

    # Start from actual
    all_teams = set()
    for event in state.events:
        for entry in event.entries:
            if entry.athlete.team:
                all_teams.add(entry.athlete.team)

    for team in all_teams:
        base = actual.get(team, TeamScore(team=team, gender=gender)).actual_points
        ceilings[team] = base

    # Upcoming finals — use top-12 seeds to capture dark horse potential
    for event in state.get_upcoming_finals(gender):
        entries = _get_finalist_entries(event, state, gender, n_finalists=12)
        if not entries:
            continue

        # Rank all 12 entries by seed to assign seed positions 1-12
        ranked_all = sorted(entries, key=lambda e: _seed_sort_key(e, event))

        # Build per-team list of (seed_position, max_place_allowed)
        # seed positions 1-8: can place 1st; 9-12: capped at 5th (4pts max)
        team_athletes: dict[str, list[int]] = defaultdict(list)
        for seed_pos, entry in enumerate(ranked_all, start=1):
            if seed_pos <= 8:
                max_place = 1      # can win
            elif seed_pos <= 12:
                max_place = 5      # capped at 5th (4pts)
            else:
                continue           # excluded
            team_athletes[entry.athlete.team].append(max_place)

        # For each team, assign their athletes the best consecutive places
        # allowed by their individual caps
        for team, caps in team_athletes.items():
            caps.sort()  # best cap first (lowest place number = best finish)
            team_pts = 0
            next_place = 1  # next available place to assign
            for cap in caps:
                # Assign this athlete the better of next_place or their cap
                assigned = max(next_place, cap)
                pts = PLACE_POINTS.get(assigned, 0)
                team_pts += pts
                next_place = assigned + 1
            ceilings[team] += team_pts

    return dict(ceilings)


# ---------------------------------------------------------------------------
# 3. Seed-based projection
# ---------------------------------------------------------------------------

def compute_seed_projection(
    actual: dict[str, TeamScore],
    state: MeetState,
    gender: Gender
) -> dict[str, int]:
    """
    Rank athletes in each upcoming final by their effective seed mark.
    Assign points by projected finish position.
    Handles ties by splitting points (average of tied places).
    """
    projections: dict[str, int] = defaultdict(int)

    for team, ts in actual.items():
        projections[team] = ts.actual_points

    for event in state.get_upcoming_finals(gender):
        # Use top-8 seeds only as projected finalists
        finalist_entries = _get_finalist_entries(event, state, gender)
        if not finalist_entries:
            continue
        # Temporarily substitute entries for ranking
        orig_entries = event.entries
        event.entries = finalist_entries
        ranked = _rank_entries_by_seed(event)
        event.entries = orig_entries

        # Check for ties (same mark)
        place = 1
        i = 0
        while i < len(ranked) and place <= 8:
            # Find group of tied entries
            j = i + 1
            current_key = _seed_sort_key(ranked[i], event)
            while j < len(ranked) and abs(_seed_sort_key(ranked[j], event) - current_key) < 0.001:
                j += 1

            tied_count = j - i
            tied_places = list(range(place, min(place + tied_count, 9)))
            avg_pts = sum(PLACE_POINTS.get(p, 0) for p in tied_places) / len(tied_places) if tied_places else 0

            for entry in ranked[i:j]:
                if any(PLACE_POINTS.get(p, 0) > 0 for p in tied_places):
                    projections[entry.athlete.team] = projections.get(entry.athlete.team, 0) + avg_pts

            place += tied_count
            i = j

    return dict(projections)


# ---------------------------------------------------------------------------
# 4. Leverage index
# ---------------------------------------------------------------------------

def compute_leverage_index(
    state: MeetState,
    gender: Gender,
    actual: dict[str, TeamScore],
    top4_probs: dict[str, float] = None,
) -> list[dict]:
    """
    Three-component leverage score for remaining finals:

    Leverage = (Swing × Contest) + (Runaway × RUNAWAY_WEIGHT)

    Contenders = teams with >15% top-4 finish probability (from Monte Carlo).
    Falls back to top-4 by actual points if top4_probs not available.

    Runaway is position-aware: checks all 4 positions for clinching potential,
    uses the highest runaway score and labels the position it came from.
    """
    TOP4_PROB_THRESHOLD = 0.15
    RUNAWAY_WEIGHT = 5

    results = []

    # Determine contenders
    sorted_teams = sorted(actual.items(), key=lambda x: x[1].actual_points, reverse=True)
    if not sorted_teams:
        return []

    if top4_probs:
        contenders = [t for t, p in top4_probs.items() if p >= TOP4_PROB_THRESHOLD]
        # Ensure at least 4 teams always shown
        if len(contenders) < 4:
            contenders = [t for t, _ in sorted_teams[:4]]
    else:
        contenders = [t for t, _ in sorted_teams[:4]]

    # Current standings for runaway calculations
    standings = [(t, ts.actual_points) for t, ts in sorted_teams]

    # Pre-compute upside for all teams
    upside_all = compute_optimistic_ceiling(actual, state, gender)

    def _team_event_upside(team, entries_12, seed_pos_map):
        """Helper: compute upside pts for a team in one event."""
        team_caps = []
        for entry in entries_12:
            if entry.athlete.team != team:
                continue
            seed_pos = seed_pos_map.get(entry.athlete.name, 99)
            if seed_pos <= 8:
                team_caps.append(1)
            elif seed_pos <= 12:
                team_caps.append(5)
        team_caps.sort()
        pts = 0
        next_place = 1
        for cap in team_caps:
            assigned = max(next_place, cap)
            pts += PLACE_POINTS.get(assigned, 0)
            next_place = assigned + 1
        return pts

    def _team_event_seeds_hold(team, entries_8, tie_pts_map):
        return sum(tie_pts_map.get(e.athlete.name, 0)
                   for e in entries_8 if e.athlete.team == team)

    for event in state.get_upcoming_finals(gender):
        entries_8 = _get_finalist_entries(event, state, gender, n_finalists=8)
        entries_12 = _get_finalist_entries(event, state, gender, n_finalists=12)
        if not entries_12:
            continue

        ranked_8 = sorted(entries_8, key=lambda e: _seed_sort_key(e, event))
        ranked_12 = sorted(entries_12, key=lambda e: _seed_sort_key(e, event))
        seed_pos_map = {e.athlete.name: i + 1 for i, e in enumerate(ranked_12)}

        # Filter: only include if at least one contender has a top-12 seed
        contenders_in_event = [
            t for t in contenders
            if any(e.athlete.team == t for e in entries_12)
        ]
        if not contenders_in_event:
            continue

        # Build seeds-hold tie-points map
        tie_pts_map: dict[str, float] = {}
        place = 1
        i = 0
        while i < len(ranked_8) and place <= 8:
            j = i + 1
            current_key = _seed_sort_key(ranked_8[i], event)
            while j < len(ranked_8) and abs(_seed_sort_key(ranked_8[j], event) - current_key) < 0.001:
                j += 1
            tied_count = j - i
            tied_places = list(range(place, min(place + tied_count, 9)))
            avg_pts = sum(PLACE_POINTS.get(p, 0) for p in tied_places) / len(tied_places) if tied_places else 0
            for e in ranked_8[i:j]:
                tie_pts_map[e.athlete.name] = avg_pts
            place += tied_count
            i = j

        # --- Component 1: Swing ---
        swing_total = 0.0
        for team in contenders_in_event:
            seeds_hold = _team_event_seeds_hold(team, entries_8, tie_pts_map)
            upside = _team_event_upside(team, entries_12, seed_pos_map)
            swing_total += max(0, upside - seeds_hold)

        # --- Component 2: Contest ---
        contenders_with_top8 = sum(
            1 for t in contenders
            if any(e.athlete.team == t for e in entries_8)
        )
        contest = contenders_with_top8 / max(len(contenders), 4)

        # --- Component 3: Position-aware Runaway ---
        # Check each position gap (1st→2nd, 2nd→3rd, 3rd→4th, 4th→5th)
        best_runaway = 0.0
        clinch_position = None

        for pos_idx in range(min(4, len(standings))):
            pos_team, pos_pts = standings[pos_idx]
            next_team, next_pts = standings[pos_idx + 1] if pos_idx + 1 < len(standings) else (None, 0)
            if not next_team:
                continue

            gap = pos_pts - next_pts
            pos_team_event_proj = _team_event_seeds_hold(pos_team, entries_8, tie_pts_map)

            # Chaser's ceiling after this event
            next_upside_here = _team_event_upside(next_team, entries_12, seed_pos_map)
            next_ceiling = upside_all.get(next_team, 0)
            next_ceiling_after = next_ceiling - next_upside_here

            gap_after = (pos_pts + pos_team_event_proj) - next_pts
            denominator = max(next_ceiling_after - gap_after, 1)
            runaway = pos_team_event_proj / denominator

            if runaway > best_runaway:
                best_runaway = runaway
                clinch_position = pos_idx + 1  # 1-indexed position being clinched

        # --- Combined Score ---
        leverage_score = (swing_total * contest) + (best_runaway * RUNAWAY_WEIGHT)

        # Narrative tag
        runaway_contribution = best_runaway * RUNAWAY_WEIGHT
        if runaway_contribution > swing_total * contest and clinch_position:
            ordinals = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}
            narrative = f"🔒 Clinching {ordinals.get(clinch_position, str(clinch_position))}"
        elif contest >= 0.5:
            narrative = "🔥 Contested"
        else:
            narrative = "📈 Swing"

        # --- Collect athlete/team detail for expander UI ---
        # Top seeded athletes overall (for fan scouting)
        top_athletes = []
        for entry in ranked_12[:8]:
            top_athletes.append({
                "name": entry.athlete.name,
                "team": entry.athlete.team,
                "seed_rank": seed_pos_map.get(entry.athlete.name, 99),
                "seed_mark": entry.effective_seed or "N/A",
            })

        # Per-contender team breakdown: seeds_hold, upside, swing
        team_breakdown = []
        for team in contenders_in_event:
            seeds_hold = _team_event_seeds_hold(team, entries_8, tie_pts_map)
            upside = _team_event_upside(team, entries_12, seed_pos_map)
            swing = max(0, upside - seeds_hold)
            # This team's athletes in event with seed ranks
            team_athletes = [
                {
                    "name": e.athlete.name,
                    "seed_rank": seed_pos_map.get(e.athlete.name, 99),
                    "seed_mark": e.effective_seed or "N/A",
                }
                for e in entries_12 if e.athlete.team == team
            ]
            team_athletes.sort(key=lambda x: x["seed_rank"])
            team_breakdown.append({
                "team": team,
                "seeds_hold": seeds_hold,
                "upside": upside,
                "swing": swing,
                "athletes": team_athletes,
            })
        # Sort by upside descending so most dangerous team shows first
        team_breakdown.sort(key=lambda x: x["upside"], reverse=True)

        results.append({
            "event_name": event.event_name,
            "event": event,
            "leverage_score": round(leverage_score, 3),
            "swing": round(swing_total, 2),
            "contest": round(contest, 2),
            "runaway": round(best_runaway, 3),
            "clinch_position": clinch_position,
            "contenders_in_event": contenders_in_event,
            "top_teams_in_event": contenders_in_event,
            "top_athletes": top_athletes,
            "team_breakdown": team_breakdown,
            "total_pts_available": sum(PLACE_POINTS.get(p, 0) for p in range(1, min(9, len(entries_8) + 1))),
            "narrative": narrative,
            "headline": _leverage_headline(event, contenders_in_event, narrative),
            "_debug": {
                "swing_x_contest": round(swing_total * contest, 3),
                "runaway_x_weight": round(best_runaway * RUNAWAY_WEIGHT, 3),
                "clinch_position": clinch_position,
                "contest_frac": round(contest, 3),
                "n_contenders": len(contenders),
                "n_contenders_in_event": len(contenders_in_event),
            }
        })

    return sorted(results, key=lambda x: x["leverage_score"], reverse=True)


def _leverage_headline(event, top_teams, narrative) -> str:
    teams_str = " & ".join(top_teams[:2]) if top_teams else "multiple teams"
    return f"{event.event_name} — {narrative} · {teams_str} both entered"


# ---------------------------------------------------------------------------
# 5. Monte Carlo win probability
# ---------------------------------------------------------------------------

# Event-type-specific probability that the top seed wins.
# Derived from NCAA D1 championship data:
#   - Sprints (60m, 200m): top seed wins ~42% in loaded fields
#   - 400m: ~38% (more tactical)
#   - Hurdles: ~45%
#   - 800m/mile: ~30% (more variable, tactical)
#   - 3000m/5000m: ~35%
#   - Field events: ~40%
#   - Relay: ~40%
# We model each athlete's win probability using a Plackett-Luce model:
# P(athlete i wins) ∝ strength_i, where strength_i derived from seed rank.

def _get_top_seed_win_prob(event: MeetEvent) -> float:
    name = event.base_event_name.lower()
    if "60m" in name and "hurdle" not in name:
        return 0.42
    elif "200m" in name:
        return 0.40
    elif "400m" in name:
        return 0.38
    elif "hurdle" in name:
        return 0.45
    elif "800m" in name:
        return 0.30
    elif "mile" in name or "1000m" in name:
        return 0.30
    elif "3000m" in name or "5000m" in name:
        return 0.35
    elif "relay" in name:
        return 0.40
    else:
        return 0.40  # field events


def _seed_rank_to_strength(rank: int, n_athletes: int, top_seed_prob: float) -> float:
    """
    Convert seed rank (1 = best) to a relative strength weight using
    an exponential decay model calibrated to top_seed_prob.
    """
    if n_athletes <= 1:
        return 1.0
    # Decay rate calibrated so that rank-1 athlete has ~top_seed_prob of winning
    # when summed over all athletes
    decay = 0.65
    raw = decay ** (rank - 1)
    return raw


def compute_win_probability(
    actual: dict[str, TeamScore],
    state: MeetState,
    gender: Gender,
    n_iterations: int = MONTE_CARLO_ITERATIONS
) -> tuple[dict[str, float], dict[str, float]]:
    """
    Monte Carlo simulation of remaining events.
    Returns two dicts:
      - win_prob:   team → probability of finishing 1st
      - top4_prob:  team → probability of finishing in top 4
    """
    upcoming = state.get_upcoming_finals(gender)

    if not upcoming:
        if not actual:
            return {}, {}, {}
        sorted_teams = sorted(actual.items(), key=lambda x: x[1].actual_points, reverse=True)
        max_pts = sorted_teams[0][1].actual_points if sorted_teams else 0
        winners = [t for t, ts in actual.items() if ts.actual_points == max_pts]
        # Static result — current standings are final
        win_prob = {t: (1.0 / len(winners) if t in winners else 0.0) for t in actual}
        top4_teams = [t for t, _ in sorted_teams[:4]]
        top4_prob = {t: (1.0 if t in top4_teams else 0.0) for t in actual}
        mc_expected = {t: ts.actual_points for t, ts in actual.items()}
        return win_prob, top4_prob, mc_expected

    # Precompute ranked entries and strengths for each upcoming event
    event_data = []
    for event in upcoming:
        finalist_entries = _get_finalist_entries(event, state, gender, n_finalists=15)
        if not finalist_entries:
            continue
        orig_entries = event.entries
        event.entries = finalist_entries
        ranked = _rank_entries_by_seed(event)
        event.entries = orig_entries
        n = len(ranked)
        top_prob = _get_top_seed_win_prob(event)
        strengths = [_seed_rank_to_strength(i + 1, n, top_prob) for i in range(n)]
        total_strength = sum(strengths)
        probs = [s / total_strength for s in strengths]
        event_data.append((event, ranked, probs))

    win_counts: dict[str, float] = defaultdict(float)
    top4_counts: dict[str, float] = defaultdict(float)
    expected_scores: dict[str, float] = defaultdict(float)
    all_teams = set(actual.keys())
    for ed in event_data:
        for entry in ed[1]:
            all_teams.add(entry.athlete.team)

    for _ in range(n_iterations):
        sim_scores: dict[str, float] = {
            t: actual.get(t, TeamScore(team=t, gender=gender)).actual_points
            for t in all_teams
        }

        for event, ranked, probs in event_data:
            remaining_entries = list(zip(ranked, probs))

            place = 1
            while remaining_entries and place <= 8:
                total = sum(p for _, p in remaining_entries)
                if total <= 0:
                    break
                r = random.random() * total
                cumulative = 0
                chosen_idx = 0
                for idx, (entry, p) in enumerate(remaining_entries):
                    cumulative += p
                    if r <= cumulative:
                        chosen_idx = idx
                        break

                winner_entry, _ = remaining_entries.pop(chosen_idx)
                pts = PLACE_POINTS.get(place, 0)
                if pts > 0:
                    sim_scores[winner_entry.athlete.team] = (
                        sim_scores.get(winner_entry.athlete.team, 0) + pts
                    )
                place += 1

        # Track win (1st) and top-4 finishes
        sorted_sim = sorted(sim_scores.items(), key=lambda x: x[1], reverse=True)
        max_score = sorted_sim[0][1] if sorted_sim else 0
        leaders = [t for t, s in sim_scores.items() if s == max_score]
        for t in leaders:
            win_counts[t] += 1.0 / len(leaders)

        # Accumulate scores for expected value
        for t, s in sim_scores.items():
            expected_scores[t] += s

        # Top-4: find the 4th place score threshold accounting for ties
        scores_sorted = sorted(sim_scores.values(), reverse=True)
        threshold = scores_sorted[3] if len(scores_sorted) >= 4 else scores_sorted[-1]
        top4_teams_sim = [t for t, s in sim_scores.items() if s >= threshold]
        # Handle ties at the bubble — split credit
        for t in top4_teams_sim:
            top4_counts[t] += 1.0 / max(1, len(top4_teams_sim) / 4)

    total = sum(win_counts.values())
    win_prob = {t: win_counts[t] / total for t in all_teams if win_counts.get(t, 0) > 0}

    top4_total = n_iterations  # each sim contributes exactly 4 "slots"
    top4_prob = {t: top4_counts[t] / top4_total for t in all_teams if top4_counts.get(t, 0) > 0}

    # Expected score = average simulated final score across all iterations
    mc_expected = {t: round(expected_scores[t] / n_iterations, 1) for t in all_teams}

    return win_prob, top4_prob, mc_expected


# ---------------------------------------------------------------------------
# 6. Scenario builder for a specific team
# ---------------------------------------------------------------------------

def compute_team_scenarios(
    team: str,
    actual: dict[str, TeamScore],
    state: MeetState,
    gender: Gender
) -> dict:
    """
    For a specific team, compute three scenarios:
    A) Seeds hold exactly — everyone finishes per seed rank
    B) Upside — team's athletes finish as high as plausible (two-tier seed cap)
    C) Worst case — team's athletes score zero remaining points

    Returns dict with scenario scores and event-by-event breakdown.
    """
    base_pts = actual.get(team, TeamScore(team=team, gender=gender)).actual_points

    scenario_a = base_pts  # seeds hold
    scenario_b = base_pts  # best case
    scenario_c = base_pts  # worst case
    event_breakdown = []

    for event in state.get_upcoming_finals(gender):
        # Get top-8 for seeds-hold projection
        finalist_entries = _get_finalist_entries(event, state, gender)
        # Get top-12 for upside/swing athlete detection
        all_entries_12 = _get_finalist_entries(event, state, gender, n_finalists=12)
        if not all_entries_12:
            continue

        ranked_all_12 = sorted(all_entries_12, key=lambda e: _seed_sort_key(e, event))
        seed_pos_map = {e.athlete.name: i + 1 for i, e in enumerate(ranked_all_12)}

        # Filter to this team's athletes in the top-12
        team_entries_12 = [e for e in all_entries_12 if e.athlete.team == team]
        if not team_entries_12:
            continue

        # Top-8 subset for seeds-hold calculation
        team_entries = [e for e in finalist_entries if e.athlete.team == team]

        # Rank top-8 finalists by seed for projection
        ranked = sorted(finalist_entries, key=lambda e: _seed_sort_key(e, event))
        rank_map = {e.athlete.name: i + 1 for i, e in enumerate(ranked)}

        # Scenario A: seeds hold — use same tie-splitting logic as compute_seed_projection
        # Group all finalists by seed value, split points among tied athletes
        a_pts = 0
        entry_details = []

        # Build tie-aware place/points map (same algorithm as compute_seed_projection)
        tie_pts_map: dict[str, float] = {}
        place = 1
        i = 0
        while i < len(ranked) and place <= 8:
            j = i + 1
            current_key = _seed_sort_key(ranked[i], event)
            while j < len(ranked) and abs(_seed_sort_key(ranked[j], event) - current_key) < 0.001:
                j += 1
            tied_count = j - i
            tied_places = list(range(place, min(place + tied_count, 9)))
            avg_pts = sum(PLACE_POINTS.get(p, 0) for p in tied_places) / len(tied_places) if tied_places else 0
            for e in ranked[i:j]:
                tie_pts_map[e.athlete.name] = avg_pts
            place += tied_count
            i = j

        for entry in team_entries:
            pts = tie_pts_map.get(entry.athlete.name, 0)
            proj_place = rank_map.get(entry.athlete.name, 9)
            a_pts += pts
            entry_details.append({
                "athlete": entry.athlete.name,
                "seed_mark": entry.effective_seed or "N/A",
                "proj_place": proj_place,
                "seed_pts": pts,
            })

        # Scenario B: Upside — two-tier cap logic using seed positions from top-12
        # Get this team's athletes with their seed positions and caps
        team_caps = []
        for entry in team_entries_12:
            seed_pos = seed_pos_map.get(entry.athlete.name, 99)
            if seed_pos <= 8:
                max_place = 1
            elif seed_pos <= 12:
                max_place = 5
            else:
                continue
            team_caps.append(max_place)

        # Assign best consecutive places within caps
        team_caps.sort()
        b_pts = 0
        next_place = 1
        for cap in team_caps:
            assigned = max(next_place, cap)
            b_pts += PLACE_POINTS.get(assigned, 0)
            next_place = assigned + 1

        # Scenario C: worst case — all athletes finish 9th or lower (0 pts)
        c_pts = 0

        # Identify Potential Swing Athletes — seeds 9-12 only
        swing_athletes = []
        for entry in team_entries_12:
            seed_pos = seed_pos_map.get(entry.athlete.name, 99)
            if 9 <= seed_pos <= 12:
                swing_athletes.append({
                    "athlete": entry.athlete.name,
                    "seed_rank": seed_pos,
                    "seed_mark": entry.effective_seed or "N/A",
                })

        scenario_a += a_pts
        scenario_b += b_pts
        scenario_c += c_pts

        event_breakdown.append({
            "event": event.event_name,
            "athletes": entry_details,
            "scenario_a_pts": a_pts,
            "scenario_b_pts": b_pts,
            "scenario_c_pts": c_pts,
            "swing_athletes": swing_athletes,
        })

    return {
        "team": team,
        "current": base_pts,
        "scenario_a": scenario_a,   # Seeds hold
        "scenario_b": scenario_b,   # Best case
        "scenario_c": scenario_c,   # Worst case
        "breakdown": event_breakdown,
    }


# ---------------------------------------------------------------------------
# Master function — run all layers at once
# ---------------------------------------------------------------------------

def run_all_analysis(state: MeetState, gender: Gender) -> dict:
    """Run all scoring layers and return a combined results dict."""
    actual = compute_actual_scores(state, gender)
    projections = compute_seed_projection(actual, state, gender)
    win_probs, top4_probs, mc_expected = compute_win_probability(actual, state, gender)
    leverage = compute_leverage_index(state, gender, actual, top4_probs)

    # All teams seen across all layers
    all_teams = set(actual.keys()) | set(projections.keys()) | set(mc_expected.keys())

    team_scores = []
    for team in sorted(all_teams):
        ts = actual.get(team, TeamScore(team=team, gender=gender))
        ts.monte_carlo_expected = mc_expected.get(team, ts.actual_points)
        ts.seed_projection = int(projections.get(team, ts.actual_points))
        ts.win_probability = round(win_probs.get(team, 0.0) * 100, 1)
        ts.top4_probability = round(top4_probs.get(team, 0.0) * 100, 1)
        team_scores.append(ts)

    # Sort by actual points descending, projection as tiebreaker
    team_scores.sort(key=lambda x: (x.actual_points, x.seed_projection), reverse=True)

    return {
        "gender": gender,
        "team_scores": team_scores,
        "leverage_index": leverage[:8],
        "actual": actual,
        "state": state,
    }

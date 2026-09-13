"""
Runs automatically 3x/week - Wednesday, Saturday, and Sunday nights (see
.github/workflows/pregame_check.yml) - covering the night before every NFL
gameday (Thu/Sun/Mon games). This is the ONLY automated job left; the full
Daily Digest is now manual-only (dashboard button or Actions tab).

Checks your STARTERS ONLY for injuries or bye weeks and, if anything needs
swapping out, suggests a specific replacement (bench first, waiver wire as
fallback). Uses Haiku 4.5 (cheap) with a hard cap on web search usage, so
this stays inexpensive even running multiple times a week.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import analyst
import sleeper_client as sc
from ntfy import send_ntfy


def player_display(player_id, players_db):
    p = players_db.get(player_id, {})
    name = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
    return {
        "name": name or player_id,
        "position": p.get("position") or "?",
        "team": p.get("team") or "FA",
        "injury_status": p.get("injury_status"),
    }


def main():
    username = os.environ["SLEEPER_USERNAME"]
    ntfy_topic = os.environ["NTFY_TOPIC"]
    league_id_override = os.environ.get("LEAGUE_ID")

    user = sc.get_user(username)
    user_id = user["user_id"]
    nfl_state = sc.get_nfl_state()
    season = nfl_state["season"]
    week = nfl_state["week"]

    league_id = league_id_override
    if not league_id:
        leagues = sc.get_user_leagues(user_id, season)
        if len(leagues) != 1:
            raise RuntimeError("Multiple/no leagues found - set the LEAGUE_ID secret.")
        league_id = leagues[0]["league_id"]

    rosters = sc.get_rosters(league_id)
    my_roster = sc.find_my_roster(rosters, user_id)
    if not my_roster:
        raise RuntimeError("Could not find your roster - check LEAGUE_ID.")

    players_db = sc.get_all_players()
    starter_ids = my_roster.get("starters") or []
    all_ids = my_roster.get("players") or []
    bench_ids = [pid for pid in all_ids if pid not in starter_ids]

    starters = [player_display(pid, players_db) for pid in starter_ids]
    bench = [player_display(pid, players_db) for pid in bench_ids]
    available = sc.get_available_players(rosters, players_db, limit=30)

    result = analyst.pregame_check(starters, bench, available, week)

    send_ntfy(
        ntfy_topic,
        f"Pregame check - Week {week}",
        result,
        tags=["football"],
    )
    print("Pregame check sent.")


if __name__ == "__main__":
    main()

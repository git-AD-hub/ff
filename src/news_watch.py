"""
Runs frequently (every few hours) and does ONE thing: watches for injury/status
changes on your roster and sends an immediate alert with AI context on whether
it actually matters. This is intentionally separate from daily_digest.py so
you get real-time-ish news without your phone buzzing all day for routine stuff -
that's what the once-a-day digest is for.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import analyst
import sleeper_client as sc
from ntfy import send_ntfy
from state import load_state, save_state


def main():
    username = os.environ["SLEEPER_USERNAME"]
    ntfy_topic = os.environ["NTFY_TOPIC"]
    league_id_override = os.environ.get("LEAGUE_ID")

    state = load_state()

    user = sc.get_user(username)
    user_id = user["user_id"]
    nfl_state = sc.get_nfl_state()
    season = nfl_state["season"]

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
    my_player_ids = my_roster.get("players") or []

    prev_status = state["player_status"]
    new_status = dict(prev_status)
    alerts = []

    for pid in my_player_ids:
        p = players_db.get(pid, {})
        cur = p.get("injury_status")
        old = prev_status.get(pid)
        new_status[pid] = cur
        if cur == old:
            continue
        if not cur and not old:
            continue

        name = p.get("full_name") or f"{p.get('first_name','')} {p.get('last_name','')}".strip()
        position = p.get("position") or "?"
        team = p.get("team") or "FA"
        analysis = analyst.player_news_alert(name, position, team, old, cur)
        alerts.append(f"{name} ({position}, {team}): {analysis}")

    if alerts:
        send_ntfy(
            ntfy_topic,
            "Player news on your roster",
            "\n\n".join(alerts),
            tags=["warning", "football"],
            priority="high",
        )
        print(f"Sent {len(alerts)} news alert(s).")
    else:
        print("No player news to report this run.")

    state["player_status"] = new_status
    save_state(state)


if __name__ == "__main__":
    main()

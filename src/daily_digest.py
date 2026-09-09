"""
Runs once a day (9am CT - see .github/workflows/daily_check.yml). Sends ONE
consolidated notification covering:
 - roster changes since yesterday (waiver claim landed, trade completed)
 - any new trade needing your decision (AI accept/decline verdict)
 - day-specific analysis:
     Tuesday: waiver targets + trade opportunities against other teams
     Wednesday: fresh waiver targets (after your league's overnight processing)
     Saturday: final start/sit call
Also writes data/player_insights.json - a small cached AI summary (opponent,
rough projection, bye week) that the dashboard reads, since Sleeper's API has
no projections/schedule data of its own and we don't want the browser calling
the Anthropic API directly (that would expose your API key on a public page).

Player-news alerts (injury changes) are handled separately and more frequently
by news_watch.py, so this script does NOT re-report those.
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import analyst
import sleeper_client as sc
from ntfy import send_ntfy
from state import load_state, save_state

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "data")
INSIGHTS_PATH = os.path.join(DATA_DIR, "player_insights.json")


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
    has_ai = bool(os.environ.get("ANTHROPIC_API_KEY"))

    state = load_state()

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
    my_player_ids = my_roster.get("players") or []
    my_players = [player_display(pid, players_db) for pid in my_player_ids]
    league = sc.get_league(league_id)
    league_settings = league.get("scoring_settings", {})

    sections = []

    # --- roster changes since yesterday ---
    prev_roster_ids = set(state["roster_player_ids"])
    cur_roster_ids = set(my_player_ids)
    added = cur_roster_ids - prev_roster_ids
    dropped = prev_roster_ids - cur_roster_ids
    if prev_roster_ids and (added or dropped):
        lines = [f"+ Added: {player_display(pid, players_db)['name']}" for pid in added]
        lines += [f"- Dropped: {player_display(pid, players_db)['name']}" for pid in dropped]
        sections.append("ROSTER CHANGES\n" + "\n".join(lines))

    # --- new trades ---
    seen_tx_ids = set(state["last_seen_transaction_ids"])
    transactions = sc.get_transactions(league_id, week)
    new_tx_ids = list(seen_tx_ids)
    for tx in transactions:
        if tx.get("type") != "trade" or tx["transaction_id"] in seen_tx_ids:
            continue
        if my_roster["roster_id"] not in (tx.get("roster_ids") or []):
            continue
        new_tx_ids.append(tx["transaction_id"])
        adds = tx.get("adds") or {}
        drops = tx.get("drops") or {}
        my_gets = [player_display(pid, players_db)["name"] for pid, rid in adds.items() if rid == my_roster["roster_id"]]
        my_gives = [player_display(pid, players_db)["name"] for pid, rid in drops.items() if rid == my_roster["roster_id"]]
        is_pending = tx.get("status") == "pending"

        if has_ai and (my_gets or my_gives):
            analysis = analyst.trade_analysis(
                giving_up=my_gives or ["(nothing of mine)"],
                receiving=my_gets or ["(nothing)"],
                roster_context=", ".join(p["name"] for p in my_players),
                is_pending=is_pending,
            )
        else:
            analysis = f"Give: {', '.join(my_gives) or 'none'}\nGet: {', '.join(my_gets) or 'none'}"

        label = "TRADE OFFER - needs your decision" if is_pending else "TRADE COMPLETED"
        sections.append(f"{label}\n{analysis}")

    # --- day-specific analysis ---
    today = datetime.date.today().weekday()  # Mon=0 ... Sun=6
    if has_ai:
        if today == 1:  # Tuesday
            available = sc.get_available_players(rosters, players_db, limit=50)
            others_raw = sc.get_all_rosters_with_owners(league_id)
            other_teams = [
                {
                    "owner_name": info["owner_name"],
                    "players": [player_display(pid, players_db) for pid in info["player_ids"]],
                }
                for rid, info in others_raw.items()
                if rid != my_roster["roster_id"]
            ]
            waiver_rec = analyst.waiver_wire_suggestions(my_players, available, week, league_settings)
            sections.append(f"WAIVER TARGETS - Week {week}\n{waiver_rec}")

            trade_rec = analyst.trade_opportunity_analysis(
                my_players, other_teams, available, week, league_settings
            )
            sections.append(f"TRADE OPPORTUNITIES\n{trade_rec}")

        elif today == 2:  # Wednesday - after overnight waiver processing
            available = sc.get_available_players(rosters, players_db, limit=50)
            waiver_rec = analyst.waiver_wire_suggestions(my_players, available, week, league_settings)
            sections.append(f"WAIVER TARGETS (post-processing) - Week {week}\n{waiver_rec}")

        elif today == 5:  # Saturday
            rec = analyst.start_sit_recommendation(my_players, week, league_settings)
            sections.append(f"FINAL START/SIT CALL - Week {week}\n{rec}")

        # --- refresh cached player insights for the dashboard (every run) ---
        try:
            raw = analyst.player_insights(my_players, week, league_settings)
            parsed = json.loads(raw)
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(INSIGHTS_PATH, "w") as f:
                json.dump({"week": week, "updated": datetime.datetime.utcnow().isoformat(), "players": parsed}, f, indent=2)
        except Exception as e:
            print(f"Could not refresh player insights cache: {e}")

    # --- send ONE consolidated notification ---
    if sections:
        send_ntfy(ntfy_topic, f"Fantasy digest - Week {week}", "\n\n---\n\n".join(sections), tags=["football"])
        print(f"Sent digest with {len(sections)} section(s).")
    else:
        print("Nothing notable today - no digest sent.")

    state["user_id"] = user_id
    state["league_id"] = league_id
    state["roster_player_ids"] = list(cur_roster_ids)
    state["last_seen_transaction_ids"] = new_tx_ids
    save_state(state)


if __name__ == "__main__":
    main()

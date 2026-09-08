"""
Main entry point. Run on a schedule (see .github/workflows/daily_check.yml).

What it does each run:
 1. Resolve your Sleeper user + league + roster
 2. Compare current player injury statuses against last run -> notify on changes
 3. Compare current roster against last run -> notify if it changed (trade/waiver landed)
 4. Look for new trade transactions involving you -> AI trade analysis, notify
 5. On specific days (Tue / Sat), send a full AI start/sit recommendation
 6. Save updated state.json (committed back to the repo by the Action)
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import sleeper_client as sc
from ntfy import send_ntfy
from state import load_state, save_state

HAS_ANTHROPIC_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))
if HAS_ANTHROPIC_KEY:
    import analyst


def get_config():
    username = os.environ["SLEEPER_USERNAME"]
    ntfy_topic = os.environ["NTFY_TOPIC"]
    league_id_override = os.environ.get("LEAGUE_ID")  # optional
    return username, ntfy_topic, league_id_override


def resolve_league(user_id, season, league_id_override):
    if league_id_override:
        return league_id_override

    leagues = sc.get_user_leagues(user_id, season)
    if len(leagues) == 1:
        return leagues[0]["league_id"]
    if len(leagues) == 0:
        raise RuntimeError(f"No NFL leagues found for this user in season {season}.")

    names = ", ".join(f"{l['name']} ({l['league_id']})" for l in leagues)
    raise RuntimeError(
        f"You're in multiple leagues this season: {names}. "
        "Set the LEAGUE_ID secret to the one you want tracked."
    )


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
    username, ntfy_topic, league_id_override = get_config()
    state = load_state()

    user = sc.get_user(username)
    user_id = user["user_id"]

    nfl_state = sc.get_nfl_state()
    season = nfl_state["season"]
    week = nfl_state["week"]

    league_id = resolve_league(user_id, season, league_id_override)
    rosters = sc.get_rosters(league_id)
    my_roster = sc.find_my_roster(rosters, user_id)
    if not my_roster:
        raise RuntimeError("Could not find your roster in this league - check LEAGUE_ID.")

    players_db = sc.get_all_players()
    my_player_ids = my_roster.get("players") or []
    my_players = [player_display(pid, players_db) for pid in my_player_ids]

    notifications = []

    # --- 1. Injury status changes ---
    prev_status = state["player_status"]
    new_status = {}
    for pid in my_player_ids:
        p = players_db.get(pid, {})
        cur = p.get("injury_status")
        new_status[pid] = cur
        old = prev_status.get(pid)
        if cur != old and (cur or old):
            name = player_display(pid, players_db)["name"]
            if cur and not old:
                notifications.append((f"Injury update: {name}", f"{name} is now listed as {cur}.", "warning"))
            elif old and not cur:
                notifications.append((f"Injury update: {name}", f"{name}'s injury designation was cleared.", "white_check_mark"))
            else:
                notifications.append((f"Injury update: {name}", f"{name} status changed: {old} -> {cur}.", "warning"))

    # --- 2. Roster changes (waiver claim / trade landed) ---
    prev_roster_ids = set(state["roster_player_ids"])
    cur_roster_ids = set(my_player_ids)
    added = cur_roster_ids - prev_roster_ids
    dropped = prev_roster_ids - cur_roster_ids
    if prev_roster_ids and (added or dropped):
        lines = []
        for pid in added:
            lines.append(f"+ Added: {player_display(pid, players_db)['name']}")
        for pid in dropped:
            lines.append(f"- Dropped: {player_display(pid, players_db)['name']}")
        notifications.append(("Your roster changed", "\n".join(lines), "arrows_counterclockwise"))

    # --- 3. New trades involving me ---
    seen_tx_ids = set(state["last_seen_transaction_ids"])
    transactions = sc.get_transactions(league_id, week)
    new_tx_ids = list(seen_tx_ids)
    for tx in transactions:
        if tx.get("type") != "trade":
            continue
        if tx["transaction_id"] in seen_tx_ids:
            continue
        if my_roster["roster_id"] not in (tx.get("roster_ids") or []):
            continue

        new_tx_ids.append(tx["transaction_id"])
        adds = tx.get("adds") or {}
        drops = tx.get("drops") or {}
        my_gets = [player_display(pid, players_db)["name"] for pid, rid in adds.items() if rid == my_roster["roster_id"]]
        my_gives = [player_display(pid, players_db)["name"] for pid, rid in drops.items() if rid == my_roster["roster_id"]]
        is_pending = tx.get("status") == "pending"

        if HAS_ANTHROPIC_KEY and (my_gets or my_gives):
            analysis = analyst.trade_analysis(
                giving_up=my_gives or ["(nothing of mine)"],
                receiving=my_gets or ["(nothing)"],
                roster_context=", ".join(p["name"] for p in my_players),
                is_pending=is_pending,
            )
        else:
            analysis = f"Give: {', '.join(my_gives) or 'none'}\nGet: {', '.join(my_gets) or 'none'}"

        title = "Trade offer - needs your decision" if is_pending else "Trade completed"
        notifications.append((title, analysis, "handshake"))

    # --- 4. Scheduled full start/sit recap (Tue = early look, Sat = final call) ---
    today = datetime.date.today().weekday()  # Mon=0 ... Sun=6
    if HAS_ANTHROPIC_KEY and today in (1, 5):  # Tuesday, Saturday
        league = sc.get_league(league_id)
        rec = analyst.start_sit_recommendation(
            roster_players=my_players,
            week=week,
            league_settings=league.get("scoring_settings", {}),
        )
        label = "Early lineup look" if today == 1 else "Final start/sit call"
        notifications.append((f"{label} - Week {week}", rec, "football"))

    # --- 5. Weekly waiver wire suggestions (Wednesday, after waivers process ~2am) ---
    if HAS_ANTHROPIC_KEY and today == 2:  # Wednesday
        league = sc.get_league(league_id)
        available = sc.get_available_players(rosters, players_db, limit=50)
        waiver_rec = analyst.waiver_wire_suggestions(
            roster_players=my_players,
            available_players=available,
            week=week,
            league_settings=league.get("scoring_settings", {}),
        )
        notifications.append((f"Waiver wire targets - Week {week}", waiver_rec, "mag"))

    # --- send everything ---
    for title, message, tag in notifications:
        send_ntfy(ntfy_topic, title, message, tags=[tag])
        print(f"Sent: {title}")

    if not notifications:
        print("No changes to report this run.")

    # --- persist state ---
    state["user_id"] = user_id
    state["league_id"] = league_id
    state["player_status"] = new_status
    state["roster_player_ids"] = list(cur_roster_ids)
    state["last_seen_transaction_ids"] = new_tx_ids
    save_state(state)


if __name__ == "__main__":
    main()

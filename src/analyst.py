"""
Calls the Claude API (with web search enabled) to turn raw Sleeper facts
(roster, injury flags, transaction details) into an actual recommendation.
Sleeper's API has no projections/rankings/news feed, so this is where the
real analysis happens - Claude looks up current matchup/injury context itself.
"""
import os
import requests

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"


def _call_claude(system_prompt, user_prompt, max_tokens=1200):
    api_key = os.environ["ANTHROPIC_API_KEY"]
    resp = requests.post(
        API_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "tools": [{"type": "web_search_20250305", "name": "web_search"}],
        },
        timeout=90,
    )
    resp.raise_for_status()
    data = resp.json()
    text_parts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    return "\n".join(text_parts).strip()


def start_sit_recommendation(roster_players, week, league_settings):
    """
    roster_players: list of dicts like
      {"name": "...", "position": "RB", "team": "...", "injury_status": "..."}
    """
    roster_lines = "\n".join(
        f"- {p['name']} ({p['position']}, {p['team']})"
        + (f" - INJURY STATUS: {p['injury_status']}" if p.get("injury_status") else "")
        for p in roster_players
    )
    system = (
        "You are a sharp, concise fantasy football advisor. Use web search to check "
        "current injury news, matchups, and recent performance for the players listed. "
        "Be direct and opinionated, not wishy-washy. Keep the whole reply under 250 words, "
        "formatted for a push notification (short lines, no markdown headers)."
    )
    user = (
        f"This is my full fantasy roster for NFL week {week}. League scoring/format notes: "
        f"{league_settings}.\n\n{roster_lines}\n\n"
        "Tell me who to START and who to SIT/BENCH at each starting position, and call out "
        "anyone I should be worried about (game-time decision, bad matchup, etc). "
        "If any bye weeks or clear injuries (Out/IR) affect a starter, flag that first."
    )
    return _call_claude(system, user)


def waiver_wire_suggestions(roster_players, available_players, week, league_settings):
    """
    roster_players: my current roster (list of dicts with name/position/team/injury_status)
    available_players: top free agents from sleeper_client.get_available_players()
    """
    roster_lines = "\n".join(
        f"- {p['name']} ({p['position']}, {p['team']})"
        + (f" - INJURY STATUS: {p['injury_status']}" if p.get("injury_status") else "")
        for p in roster_players
    )
    available_lines = "\n".join(
        f"- {p['name']} ({p['position']}, {p['team']})" for p in available_players
    )
    system = (
        "You are a sharp, concise fantasy football advisor helping with weekly waiver wire "
        "pickups. Use web search to check bye weeks for week " + str(week + 1) + ", current "
        "injury news, snap counts/usage trends, and upcoming matchups. Be direct about who is "
        "actually worth an FAAB bid vs. a free add. Keep the whole reply under 300 words, "
        "formatted for a push notification (short lines, no markdown headers)."
    )
    user = (
        f"My current roster (week {week}), league scoring/format notes: {league_settings}.\n\n"
        f"{roster_lines}\n\n"
        f"Available free agents in my league (already filtered to the more relevant/rosterable "
        f"names by Sleeper's own ranking):\n{available_lines}\n\n"
        "First, identify weak spots on my roster for the UPCOMING week — anyone injured "
        "(Questionable/Doubtful/Out/IR) or on a bye. Then recommend the top 3-5 available "
        "players I should actually bid on, prioritized, explaining briefly why each one "
        "(matches a need, hot streak, favorable matchup, etc). If nothing on the list is worth "
        "a real bid, say so plainly instead of padding the list."
    )
    return _call_claude(system, user, max_tokens=1400)


def player_news_alert(name, position, team, old_status, new_status):
    """
    Called the moment a rostered player's injury_status changes. Uses web search
    to find out WHAT actually happened and whether it's roster-relevant, rather
    than just reporting the raw status change.
    """
    system = (
        "You are a fantasy football advisor. Use web search to find out what actually "
        "happened with this player in the last day or two. Keep it under 90 words, "
        "formatted for a push notification, no markdown headers. End with a one-line "
        "verdict starting with 'ACTION:' - either 'ACTION: monitor only', "
        "'ACTION: consider benching/handcuff', or 'ACTION: consider trading/dropping now'."
    )
    user = (
        f"{name} ({position}, {team}) on my fantasy roster just changed injury status "
        f"from '{old_status or 'healthy'}' to '{new_status or 'healthy'}'. What happened, "
        "and does this actually require me to do anything with my roster?"
    )
    return _call_claude(system, user, max_tokens=400)


def trade_opportunity_analysis(my_players, other_teams, available_players, week, league_settings):
    """
    other_teams: list of {"owner_name": str, "players": [player dicts]}
    """
    my_lines = "\n".join(f"- {p['name']} ({p['position']}, {p['team']})" for p in my_players)
    teams_block = "\n\n".join(
        f"{t['owner_name']}:\n" + "\n".join(f"  - {p['name']} ({p['position']})" for p in t["players"])
        for t in other_teams
    )
    available_lines = "\n".join(
        f"- {p['name']} ({p['position']}, {p['team']})" for p in available_players
    )
    system = (
        "You are a sharp, honest fantasy football trade strategist. Use web search for "
        "current player values, roles, and injury/depth-chart context. Look for realistic "
        "win-win trades, not just what benefits me. Keep the whole reply under 350 words, "
        "formatted for a push notification (short lines, no markdown headers)."
    )
    user = (
        f"League scoring/format notes: {league_settings}. It's week {week}.\n\n"
        f"My roster:\n{my_lines}\n\n"
        f"Other teams in my league:\n{teams_block}\n\n"
        f"Also available on waivers right now:\n{available_lines}\n\n"
        "Identify my 1-3 biggest roster weaknesses right now. Then look at the other teams' "
        "rosters for realistic trade targets that address those weaknesses - ideally where the "
        "other owner also has a surplus at that position or a need I could fill from my own "
        "depth. For each suggestion, name exactly which players to offer and request, and why "
        "the other owner might reasonably say yes. If no trade genuinely makes sense this week, "
        "say so plainly rather than forcing a suggestion."
    )
    return _call_claude(system, user, max_tokens=1600)


def player_insights(my_players, week, league_settings):
    """
    Generates a compact JSON blob of per-player context (opponent, approx projection,
    bye week, and a short note) for the dashboard to display. Returns raw text - caller
    should attempt to json.loads() it and handle failure gracefully, since the model
    is asked for JSON but this isn't a guaranteed-structured API.
    """
    roster_lines = "\n".join(
        f"- {p['name']} ({p['position']}, {p['team']})" for p in my_players
    )
    system = (
        "You are a fantasy football data assistant. Use web search to find each player's "
        "week " + str(week) + " opponent, whether they're on a bye this week or soon, and a "
        "rough expected fantasy point range given the matchup. Respond with ONLY a JSON array, "
        "no other text, no markdown code fences. Each item: "
        '{"name": str, "opponent": str, "bye_week": int or null, "projection_low": number, '
        '"projection_high": number, "note": short string}. If a player is on a bye, set '
        'opponent to "BYE" and projections to 0.'
    )
    user = f"League scoring notes: {league_settings}. My roster:\n{roster_lines}"
    raw = _call_claude(system, user, max_tokens=2000)
    # strip accidental code fences if the model adds them anyway
    return raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()


def trade_analysis(giving_up, receiving, roster_context, is_pending):
    give_lines = "\n".join(f"- {p}" for p in giving_up)
    get_lines = "\n".join(f"- {p}" for p in receiving)
    status_note = (
        "This trade is PENDING - I still need to decide whether to accept it."
        if is_pending
        else "This trade already went through (informational recap only)."
    )
    system = (
        "You are a sharp, honest fantasy football trade analyst. Use web search for current "
        "player values, injury status, and rest-of-season outlook. Give a clear verdict "
        "(ACCEPT / DECLINE / IT'S CLOSE) up front, then 3-5 short bullet points of reasoning. "
        "Keep it under 200 words, formatted for a push notification."
    )
    user = (
        f"{status_note}\n\nI would give up:\n{give_lines}\n\nI would receive:\n{get_lines}\n\n"
        f"My roster context: {roster_context}\n\n"
        "Should I accept this trade? Consider rest-of-season value, my roster needs, and injury risk."
    )
    return _call_claude(system, user)

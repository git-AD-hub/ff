"""
Thin wrapper around the public, read-only Sleeper API.
Docs: https://docs.sleeper.com/
No authentication is required or possible - Sleeper's API is read-only.
"""
import json
import os
import time
import requests

BASE = "https://api.sleeper.app/v1"
CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "cache")
os.makedirs(CACHE_DIR, exist_ok=True)
PLAYERS_CACHE_PATH = os.path.join(CACHE_DIR, "players.json")
PLAYERS_CACHE_MAX_AGE_SECONDS = 20 * 60 * 60  # refresh at most ~once/day per Sleeper's guidance


def _get(path, params=None):
    resp = requests.get(f"{BASE}{path}", params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


def get_user(username_or_id):
    """Returns {'user_id', 'username', 'display_name', 'avatar'}"""
    return _get(f"/user/{username_or_id}")


def get_user_leagues(user_id, season, sport="nfl"):
    return _get(f"/user/{user_id}/leagues/{sport}/{season}")


def get_league(league_id):
    return _get(f"/league/{league_id}")


def get_rosters(league_id):
    return _get(f"/league/{league_id}/rosters")


def get_league_users(league_id):
    return _get(f"/league/{league_id}/users")


def get_matchups(league_id, week):
    return _get(f"/league/{league_id}/matchups/{week}")


def get_transactions(league_id, week):
    return _get(f"/league/{league_id}/transactions/{week}")


def get_nfl_state():
    """Returns current season/week info, e.g.
    {'week': 2, 'season_type': 'regular', 'season': '2026', ...}"""
    return _get("/state/nfl")


def get_all_players(sport="nfl", force_refresh=False):
    """
    Full player dictionary keyed by player_id. ~5MB. Sleeper explicitly asks
    that this NOT be called more than once/day, so we cache it to disk.
    """
    if not force_refresh and os.path.exists(PLAYERS_CACHE_PATH):
        age = time.time() - os.path.getmtime(PLAYERS_CACHE_PATH)
        if age < PLAYERS_CACHE_MAX_AGE_SECONDS:
            with open(PLAYERS_CACHE_PATH) as f:
                return json.load(f)

    data = _get(f"/players/{sport}")
    with open(PLAYERS_CACHE_PATH, "w") as f:
        json.dump(data, f)
    return data


def find_my_roster(rosters, user_id):
    for r in rosters:
        if r.get("owner_id") == user_id:
            return r
    return None


RELEVANT_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}


def get_available_players(rosters, players_db, limit=50):
    """
    Returns the top `limit` free agents (not on ANY roster in the league),
    ranked by Sleeper's own 'search_rank' (lower = more relevant/rosterable),
    so the AI prompt gets a manageable, meaningfully-sorted list instead of
    every unrostered player in the NFL (which is thousands of names).
    """
    rostered_ids = set()
    for r in rosters:
        for pid in (r.get("players") or []):
            rostered_ids.add(pid)

    candidates = []
    for pid, p in players_db.items():
        if pid in rostered_ids:
            continue
        if p.get("position") not in RELEVANT_POSITIONS:
            continue
        if p.get("status") not in ("Active", None):
            continue
        rank = p.get("search_rank")
        if rank is None:
            continue
        candidates.append((rank, pid, p))

    candidates.sort(key=lambda x: x[0])
    result = []
    for rank, pid, p in candidates[:limit]:
        result.append({
            "player_id": pid,
            "name": p.get("full_name") or f"{p.get('first_name','')} {p.get('last_name','')}".strip(),
            "position": p.get("position"),
            "team": p.get("team") or "FA",
            "search_rank": rank,
        })
    return result

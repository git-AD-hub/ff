"""
Simple JSON-file state store, committed back to the repo by the GitHub Action
after each run, so the script can tell what's CHANGED since last time
(new injury designation, new trade, roster change, etc.) instead of just
re-reporting everything every run.
"""
import json
import os

STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "state.json")

DEFAULT_STATE = {
    "user_id": None,
    "league_id": None,
    "last_seen_transaction_ids": [],
    "player_status": {},   # player_id -> last known injury_status
    "roster_player_ids": [],  # last known set of player_ids on my roster
}


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            data = json.load(f)
        merged = dict(DEFAULT_STATE)
        merged.update(data)
        return merged
    return dict(DEFAULT_STATE)


def save_state(state):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)

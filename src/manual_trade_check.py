"""
For evaluating a HYPOTHETICAL trade before you even propose/accept it in Sleeper.
Run manually from the GitHub Actions tab (workflow_dispatch inputs) -
see .github/workflows/trade_check.yml
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import analyst
from ntfy import send_ntfy


def main():
    giving_up = [x.strip() for x in os.environ["GIVING_UP"].split(",") if x.strip()]
    receiving = [x.strip() for x in os.environ["RECEIVING"].split(",") if x.strip()]
    roster_context = os.environ.get("ROSTER_CONTEXT", "")
    ntfy_topic = os.environ["NTFY_TOPIC"]

    result = analyst.trade_analysis(
        giving_up=giving_up,
        receiving=receiving,
        roster_context=roster_context,
        is_pending=True,
    )
    send_ntfy(ntfy_topic, "Hypothetical trade analysis", result, tags=["handshake", "thinking_face"])
    print(result)


if __name__ == "__main__":
    main()

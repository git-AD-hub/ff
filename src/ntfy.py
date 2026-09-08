"""
Free push notifications via ntfy.sh - no account, no API key needed.
Install the ntfy app on your iPhone and subscribe to your topic to receive these.
"""
import requests


def send_ntfy(topic, title, message, priority="default", tags=None):
    """
    priority: 'min', 'low', 'default', 'high', 'urgent'
    tags: list of emoji shortcodes, e.g. ['warning', 'football']
    """
    headers = {"Title": title, "Priority": priority}
    if tags:
        headers["Tags"] = ",".join(tags)

    resp = requests.post(
        f"https://ntfy.sh/{topic}",
        data=message.encode("utf-8"),
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    return resp

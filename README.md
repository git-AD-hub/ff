# Sleeper Fantasy Football Assistant

Tracks your Sleeper roster, alerts you (via free push notification) when a
player's injury status changes or a trade shows up, and sends AI-generated
start/sit and trade-accept/decline recommendations. Runs automatically on
GitHub's free infrastructure — nothing needs to stay on on your PC or phone.

## What you get
- **Automatic checks every 6 hours** for injury news, roster changes, and new trades
- **Push notifications** via [ntfy.sh](https://ntfy.sh) (free, no account)
- **AI start/sit recommendations** every Tuesday (early look) and Saturday (final call)
- **AI trade analysis** automatically when a trade involving you appears in Sleeper,
  or manually for a hypothetical trade you're considering
- **Weekly waiver wire targets** every Wednesday morning, right after waivers process —
  flags any of your players who are injured or on bye, and suggests who to bid on from
  the available pool to cover those spots
- **A mobile dashboard** you can pin to your iPhone home screen showing your live roster

## One-time setup (about 15 minutes)

### 1. Install ntfy on your iPhone
- Get the free **ntfy** app from the App Store
- Open it, tap **+**, and subscribe to the topic: `lesssgeaux-ff-alerts-2026`
- That's it — anything sent to that topic now pops up on your phone

### 2. Get a free Anthropic API key (for the AI analysis)
- Go to [console.anthropic.com](https://console.anthropic.com), create a key
- This is a *separate* thing from your claude.ai subscription — it's pay-as-you-go,
  and this app's usage will cost well under $1/month (a few cents per check)
- **Optional**: if you skip this, the app still works — it just sends raw facts
  (injury status, trade adds/drops) instead of AI-written analysis

### 3. Create the GitHub repo
1. Go to [github.com/new](https://github.com/new), create a **private** repo
   (private keeps your league details out of public view)
2. Upload every file from this project, keeping the folder structure
   (`src/`, `.github/workflows/`, `docs/`, plus the root files)
3. Commit

### 4. Add your secrets
In your new repo: **Settings → Secrets and variables → Actions → New repository secret**.
Add each of these:

| Secret name | Value |
|---|---|
| `SLEEPER_USERNAME` | `LesssGeaux` |
| `NTFY_TOPIC` | `lesssgeaux-ff-alerts-2026` |
| `ANTHROPIC_API_KEY` | your key from step 2 (optional but recommended) |
| `LEAGUE_ID` | only needed if you're in more than one NFL league this season — leave it unset otherwise, the app will tell you if it needs it |

### 5. Turn on Actions
- Go to the **Actions** tab of your repo → click "I understand my workflows, go ahead and enable them"
- Click into **Sleeper Check** → **Run workflow** to test it right now
- Check your phone — you should get a notification (or see "No changes to report" in the run log, which is normal and means it worked)

### 6. Turn on the dashboard (optional but nice on iPhone)
- **Settings → Pages** → set source to **Deploy from branch**, branch `main`, folder `/docs`
- After a minute your dashboard is live at `https://<your-username>.github.io/<repo-name>/`
- Open that link in Safari on your iPhone → Share → **Add to Home Screen**
- Now you have an app icon that shows your live roster whenever you tap it

## Using it day to day
- **Notifications happen automatically** — nothing to do
- **Check the dashboard** any time for your current roster/injury flags
- **Evaluating a trade before you propose it?** Go to Actions → **Trade Analyzer (manual)**
  → Run workflow → fill in who you'd give up / receive → you'll get a push notification
  with the verdict within about a minute

## How it works under the hood
- `src/sleeper_client.py` — talks to Sleeper's free, public, read-only API
- `src/checker.py` — the main scheduled job; diffs current vs. last-known state
- `src/analyst.py` — sends roster/trade facts to Claude (with web search enabled)
  for the actual recommendation, since Sleeper's API has no rankings/news of its own
- `src/ntfy.py` — fires the push notification
- `state.json` — remembers what's already been reported, so you don't get spammed
  with the same info every 6 hours; the Action commits this back to the repo after each run
- `.github/workflows/` — the free cron jobs that run all of this on GitHub's servers

## Adjusting the schedule
Edit the `cron` lines in `.github/workflows/daily_check.yml`. It's currently every
6 hours, plus a guaranteed Wednesday 9am ET run timed to land safely after most
leagues' 2am waiver processing. Cron time is UTC — if your league processes waivers
at a very different time or you're not in Central/Eastern time, adjust the
`0 13 * * 3` line accordingly (13:00 UTC = 9am ET / 8am CT). You can also just
click **Run workflow** any time to trigger it manually.

Note: Sleeper doesn't expose exact league-specific waiver processing times through
the API, so this is timed with a safety buffer rather than an exact trigger — if
your commissioner has set an unusual waiver day/time, check your league settings
in the Sleeper app and adjust the cron line to match.

## Costs
- GitHub Actions: free for private repos at this usage level (a few thousand
  minutes/month free; this uses a few minutes/day)
- ntfy.sh: free
- Anthropic API: roughly $0.01–0.05 per AI analysis call, so a few dollars for
  the whole season at most

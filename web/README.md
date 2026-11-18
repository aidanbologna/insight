# Insight by Milton on the web

A small server that lets anyone with a browser (Chromebook, Mac, iPad, phone) open Insight by Milton
from a link. Nothing to install and no account. The Windows app is unchanged.

This folder is **phase 0** of [the plan](../docs/web-version-plan.md): the skeleton and one real page,
built to prove the path from a browser to live market data. It is not online yet. Putting it online
needs a hosting account, which only you can create. The steps are [below](#putting-it-on-render).

## What is here

| File | What it does |
|---|---|
| `../insight_core.py` | The data code, shared with the Windows app: downloads, cache, ratings, wording, colours. |
| `app.py` | The server: the answers below and the pages. |
| `source.py` | The one doorway to market data (`MarketSource`). Everything goes through it. |
| `yahoo.py` | Yahoo Finance behind that doorway, using `insight_core`. |
| `service.py` | The shared cache, the ceiling on how fast Yahoo is asked, the back-off, the counters. |
| `limits.py` | The request limit for each visitor, and the checks on what visitors type. |
| `shape.py` | Turns downloaded data into what the pages receive. |
| `config.py` | The numbers you can tune without touching code. |
| `static/` | The Home page and the Status page: plain HTML, CSS and JavaScript. |
| `tests/` | Automated tests. They use made-up data and never contact Yahoo. |
| `../Dockerfile`, `../render.yaml` | Instructions the host uses to build and run the server. |

## Run it on this computer

```
pip install -r web/requirements.txt
python -m web
```

Then open <http://127.0.0.1:8000>. Stop it with Ctrl+C. The Status page is at `/status`.

To run the tests:

```
pip install pytest httpx
python -m pytest web/tests
```

## What the server answers

All answers are plain data (JSON). Each one says when its numbers were fetched (`as_of`) and whether
they are older than they should be (`stale`, with a sentence in `notice` explaining why).

| Address | Answer |
|---|---|
| `/api/health` | "ok". Never contacts Yahoo, so the host can check it as often as it likes. |
| `/api/snapshot` | The Home page: date, market open or closed, today's brief, the eight snapshot cards with sparklines. |
| `/api/quotes?symbols=AAPL,MSFT` | Latest price, day change and a one-month sparkline for up to 25 symbols. |
| `/api/history/AAPL?range=1Y` | Price bars for 1D, 5D, 1M, 6M, YTD, 1Y, 5Y or MAX, with the 50 and 200 day averages. |
| `/api/stock/AAPL` | One stock: name, price, key statistics, fundamentals ratings, earnings with the written summary. |
| `/api/search?q=costco` | Tickers that match a company name. |
| `/api/status` | How the data fetches have gone since the server started. `/status` shows it as a page. |

## How it protects Yahoo and itself

- **One cache for everyone**, with the lifetimes the Windows app uses: prices 55 seconds, daily
  charts 15 minutes, intraday charts 1 minute, company details 5 minutes, earnings 6 hours.
  Thirty students opening the same stock cause one download.
- **Shared downloads.** People who ask for the same thing at the same moment wait for one download
  instead of starting their own.
- **A ceiling** on how fast Yahoo is asked: 120 requests a minute on average, 30 at once. Past that,
  requests wait their turn for up to 8 seconds, and are then told to try again.
- **Back-off.** When Yahoo answers "Too Many Requests" the server stops asking for about 3 minutes,
  doubling up to 15 if it keeps happening (the Windows app's rule). Meanwhile it serves what it
  already has, marked as older. Unlike the Windows app it asks for nothing new during the wait.
- **A limit for each visitor address**: 600 requests a minute, 120 at once. A classroom usually
  shares one address, so this is sized for a room, not a person.
- **Checked input.** A ticker must be 1 to 12 letters, digits or `. - ^ =` before anything is looked
  up. A ticker Yahoo doesn't know is remembered for 2 minutes so a typo isn't asked about repeatedly.
- **Bounded memory.** The cache drops its oldest answers once it holds 2000 of them, or about 50 MB
  of numbers, so asking about thousands of tickers can't fill the host's memory.
- **No student data.** No accounts and no database. Visitor addresses are held in memory for the
  limit above and forgotten after ten quiet minutes.

The ceiling and the visitor limit are starting guesses. Change them with environment variables (in
Render: the service's **Environment** page):

| Variable | Default | Meaning |
|---|---|---|
| `INSIGHT_SOURCE_PER_MINUTE` | 120 | Ceiling on requests to the data source per minute |
| `INSIGHT_SOURCE_BURST` | 30 | How many may go at once after a quiet spell |
| `INSIGHT_SOURCE_MAX_WAIT` | 8 | Seconds a visitor may wait for a turn |
| `INSIGHT_VISITOR_PER_MINUTE` | 600 | Requests a minute from one address |
| `INSIGHT_VISITOR_BURST` | 120 | Requests at once from one address |
| `INSIGHT_VISITOR_ADDRESS` | `socket` | `forwarded` behind a host's proxy (set in `render.yaml`) |
| `INSIGHT_CACHE_ENTRIES` | 2000 | Answers kept in memory before the oldest are dropped |
| `INSIGHT_CACHE_NUMBERS` | 1500000 | The same limit counted in numbers, because one chart holds thousands (about 50 MB) |

## Changing the data source

All market data comes through the five methods of `MarketSource` in `source.py`: `quotes`,
`history`, `details`, `earnings` and `search`. To use another provider, write a class with those
methods (see `yahoo.py`, about 80 lines) and pass it to `create_app(source=...)`. The cache, the
limits and the pages stay as they are.

## Putting it on Render

Nothing here has been put online. These steps need your own account, so only you can do them.

1. **Commit and push this branch** (`web-version`) to GitHub. Either merge it into `main` first, or
   deploy straight from `web-version` and merge later.
2. **Create a Render account** at <https://render.com>. You can sign in with GitHub.
3. In Render choose **New > Blueprint**, connect GitHub if asked, and press **Connect** next to the
   `insight` repository.
4. Give the Blueprint a name and **choose the branch** you pushed in step 1. Render reads
   `render.yaml` from the top of the repository.
5. Review what it lists (one web service called `insight-by-milton`, free plan) and press
   **Deploy Blueprint**. The first build takes several minutes.
6. Open the address Render shows (it ends in `.onrender.com`) and check three things:
   - `/api/health` says `"status":"ok"`
   - the Home page shows prices
   - `/status` shows fetches that worked

Things to decide while you are there:

- **Region.** Render uses Oregon unless you pick another, and it can't be changed afterwards. To
  choose, add a line such as `region: ohio` or `region: virginia` under `plan:` in `render.yaml`
  before step 5.
- **Plan.** `render.yaml` asks for the free plan, which sleeps after 15 minutes without visitors and
  takes about a minute to wake. Change `plan: free` to `plan: starter` for always-on (paid).
- **Deploys.** `render.yaml` turns automatic deploys off, so the site changes only when you press
  **Manual Deploy** on the service's page. Set `autoDeployTrigger` to `commit` to deploy on every push.

## The test on the real host

Phase 0 ends with a question only the real host can answer: does Yahoo let this server's address
ask for data? Leave the Home page open in a browser during a few school days and look at `/status`.

| On the Status page | Good sign | Bad sign |
|---|---|---|
| Fetches that worked | Nearly all of them | |
| Told to slow down | 0, or rare | Regular, or "Holding back" most of the day |
| Came back empty | Only for mistyped tickers | Prices or Charts empty for real tickers |
| Memory in use | Well under 512 MB | Close to 512 MB (the free and Starter limit) |
| Visitors | The number of addresses looks like the number of places people connect from | Always 1 address while people in different places use it: `INSIGHT_VISITOR_ADDRESS` needs changing |

The counters start again whenever the server restarts, and a free plan restarts after every quiet
spell. Problems are also written to the service's **Logs** page in Render, which keeps them longer.

If Yahoo does throttle the host, the plan's answer is a different data source or a different host,
before any more pages are built.

## What has and hasn't been checked

Checked on this computer: the server starts, the Home page shows live numbers in light and dark and
at phone width, every answer above works against live Yahoo data, and the automated tests pass.

Not checked: the Docker image has not been built (Docker isn't installed here), and nothing has run
on Render. The libraries were confirmed to exist for Linux, but the first deploy is the real test.
`render.yaml` follows Render's documentation as of November 2026.

## Still open (your decisions)

- The host. Render is the suggestion; the deploy files are written for it.
- The data source. Yahoo through yfinance for now. yfinance describes Yahoo's data as for personal
  use, which a public website may not be. See the plan's risks section.
- The web address.

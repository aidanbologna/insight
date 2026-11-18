# Insight by Milton on the web: plan

*Written November 10, 2026. Status: plan agreed in outline, nothing built yet.*

## Goal

Let students on Chromebooks (and Macs, iPads and phones) use Insight by Milton by opening a link.
Nothing to install and no account. The Windows app stays as it is.

## Decision: a live server

On November 10 you chose a **live server** over a no-server site. This plan follows that choice.
A small Python program runs on a hosting service, answers each student's browser, and fetches
market data on their behalf.

What that buys compared with the no-server option: **any ticker** instead of a fixed list, prices
as fresh as the Windows app, and room for price alerts later. What it costs: a hosting account,
either a wake-up delay or a few dollars a month, and a data-source risk that shows up live instead
of as slightly old numbers. The risks section says how each is handled.

## How it works

```
 Student's browser                 Hosting service                    Data sources
 ┌─────────────────────┐   asks   ┌──────────────────────────┐ fetches ┌──────────────────┐
 │ Pages (HTML/CSS/JS)  │ ───────► │ Python server             │ ──────► │ Yahoo Finance     │
 │ Charts drawn here    │ ◄─────── │  - the app's data code    │ ◄────── │ 24 news feeds     │
 │ Watchlist, portfolio │  answers │  - one shared cache       │         │ U.S. Treasury     │
 │ saved in the browser │          │  - limits and back-off    │         │ Fed, BLS, BEA     │
 └─────────────────────┘          └──────────────────────────┘         └──────────────────┘
```

The important part is the **shared cache**. When thirty students open the same stock, the server
asks Yahoo once and answers everyone from memory. Students' devices never contact Yahoo at all, so
the school Wi-Fi limit that version 12 works around stops mattering for the web version.

## What students get, compared with the Windows app

| | Windows app | Web version |
|---|---|---|
| Works on | Windows 10/11 | Any device with a browser |
| Install | Setup file | None, open a link |
| Stocks covered | Any ticker | Any ticker |
| Price freshness | 1 to 15 minutes | About the same, shared by the whole class |
| First visit after a quiet spell | Instant | On a free hosting plan, up to about a minute while the server wakes |
| Watchlist and portfolio | Saved on the computer | Saved in that browser on that device, with export and import |
| Price alerts | Windows notifications | Later phase, while the page is open |
| Colors and themes | Yes | Yes, same themes |
| News with bias and paywall tags | Yes | Yes |
| Fundamentals ratings, earnings box | Yes | Yes |
| Bond Market, Calendar | Yes | Yes |
| Chart screenshots, CSV import | Yes | Later phase |

## The server

- **Shared data code.** The data code moves out of `insightByMilton.py` into its own module that
  both the desktop app and the server import. The desktop app keeps working exactly as now.
- **Answers it gives.** Market snapshot, quotes, price history by range, a stock's details with
  fundamentals ratings and earnings, ticker search, movers, news by outlet and by stock, Treasury
  yields, the calendar, and Milton Review articles. All as plain data the pages turn into screens.
- **One cache for everyone.** Same lifetimes the desktop app uses: prices about a minute, daily
  history 15 minutes, company details 5 minutes, earnings 6 hours, news 10 minutes. Two students
  asking for the same thing at the same moment share one fetch.
- **Going easy on Yahoo.** A steady ceiling on how fast the server asks, plus version 12's back-off
  when Yahoo says "too many requests". During a back-off the server keeps answering from what it has.
- **Protecting itself.** A public address can be found by anyone, so each visitor gets a request
  limit and every ticker is checked before it is looked up.
- **No student data.** No accounts, no database. Nothing about students is stored on the server.
- **Swappable data source.** All market data goes through one small interface, so Yahoo can be
  replaced by a provider with a key without touching the pages.

## The pages

Plain HTML, CSS and JavaScript served by the same server, so there is one thing to deploy. The
Milton design carries over: cream background, serif headings, terracotta accent, light and dark,
and the eight color themes. Charts are drawn in the browser. Watchlist, portfolio and settings
live in the browser's own storage.

## What carries over from the current code

The app is one 8,300-line Python file. Measured split:

| Part | Lines | For the web |
|---|---|---|
| Data code: fetching, fundamentals rules, earnings summaries, news matching, calendar | about 880 | Reused as it is, on the server |
| Brand and content: colors, outlet list with bias ratings, glossary, symbol lists | about 650 | Reused as data |
| Formatting helpers | about 150 | Rewritten in JavaScript (small) |
| Screens: widgets, seven pages, the window | about 5,900 | Rewritten as HTML, CSS and JavaScript |

Roughly a fifth is reused directly and the screens are a rewrite. The design decisions, wording
and page structure carry over, which is the slow part of a first version.

## Hosting

Facts checked on November 10, 2026. Prices change, so confirm on each provider's own page.

| Option | Cost | Wake-up | Notes |
|---|---|---|---|
| **Render, free plan** | $0 | Sleeps after 15 minutes without visitors; waking takes roughly half a minute to a minute | Simplest setup: connect the GitHub repository and it deploys on every push. 512 MB of memory. |
| **Render, Starter** | about $7 a month | Always on | Same setup, no sleeping. |
| **Google Cloud Run** | Free allowance of 2 million requests a month, then pay per use | Sleeps when idle; wake-up time not confirmed | More setup, and needs a billing account with a card. |
| **Railway, Hobby** | $5 a month | Always on | Fee counts toward usage. |
| Hugging Face Spaces | Not free for this kind of app any more | | Ruled out. |

**Suggested start:** Render's free plan. Whoever opens the site first before class wakes it for
everyone. If the wait gets annoying, the Starter plan removes it without changing anything else.

## What you need to do yourself

I can build and test everything on this computer, but three things have to be done by you:

1. **Create the hosting account** and connect the GitHub repository to it. I cannot create
   accounts or enter payment details.
2. **Decide on a paid plan**, if the wake-up delay turns out to matter.
3. **Add a DNS record** at Wix if you want an address like `insight.themiltonreview.net`.

## Phases

**Phase 0. Skeleton and proof.**
- Split the data code into a shared module. Desktop app unchanged in behaviour, installer still builds.
- A server that runs on this computer with the first answers (snapshot, quotes, history, stock
  details, search), the shared cache and the limits.
- One real page, Home, in the Milton design, to prove the whole path from browser to data.
- Deploy files for the host, and a small status page that records how often data fetches succeed.
- **Gate:** once you have a hosting account, deploy it and watch that status page for a few school
  days. If Yahoo throttles the host, switch the data source or the host before building further.

Everything in phase 0 except the deploy can be built and tested here, before any account exists.

**Phase 1. Home and Markets.**
- Site shell: header, navigation, light and dark, the eight color themes, welcome screen.
- Home: today's brief, market snapshot, movers, Milton Review articles.
- Markets: overview, search for any ticker, stock page with chart, key statistics, fundamentals
  ratings and the earnings box. Works on a Chromebook screen and on a phone.

**Phase 2. News, Bond Market, Calendar.**

**Phase 3. Watchlist and Portfolio** in the browser, with export, import and broker CSV import.
Price alerts while the page is open.

**Phase 4. Finish.** Link from themiltonreview.net, the Ctrl+K search, chart screenshots.

Phases 1 to 3 are each a release students can already use.

## Risks

| Risk | What is known | Handling |
|---|---|---|
| Yahoo throttles the server | yfinance users report "Too Many Requests" on shared cloud addresses, including Streamlit Cloud and, in one anecdote, Render. With a live server this shows up as errors in front of students. | The shared cache keeps the request count low. The server paces itself, backs off, and keeps answering from memory. Phase 0 measures the real host before more is built. If it fails: a data provider with a key, or a different host. |
| Terms of the data | yfinance's README says it is "intended for research and educational purposes" and that Yahoo's API is "for personal use only". A public website that serves the data to others is a different situation from an app each person runs for themselves. I could not confirm Yahoo's own wording on this. | Your decision before the site is shared widely. The swappable data source keeps the alternative open. Free plans from keyed providers exist, but their limits differ between sources and display rights need checking on each provider's terms page. |
| Wake-up delay | Render's free plan sleeps after 15 minutes without traffic. | Open the site before class, or move to the Starter plan. |
| Memory | The free and Starter plans have 512 MB. The data libraries are heavy. | Charts are drawn in the browser, so the server skips the charting library. Measure in phase 0. |
| Strangers and bots | A public address gets found. | Per-visitor limits, ticker checks, and the cache. |
| Browser storage is per device | A student on a different Chromebook does not see their portfolio. | Export and import in phase 3. Accounts stay out on purpose. |
| Two versions to maintain | New features have to be built twice, or on one side only. | The shared data module keeps the logic in one place. |

## Costs

| Item | Cost |
|---|---|
| Hosting | $0 with a wake-up delay, or about $5 to $7 a month always on |
| A data provider, only if Yahoo cannot be used | Free plans exist; paid plans vary |
| `insight.themiltonreview.net` | No extra cost if the domain's DNS allows adding a record |

## The fallback: a no-server site

If the data source cannot be made reliable from a hosting service, the same pages can be fed by a
scheduled job on GitHub that writes data files every 15 to 30 minutes, with the site on GitHub
Pages. That is free and cannot be throttled per student, at the price of a fixed stock list and
older prices. The shared data module and the pages built for the live server would both be reused.

## Decisions

| | Decision | Status |
|---|---|---|
| 1 | Shape | **Live server** (chosen November 10) |
| 2 | Host | Open. Suggested: Render, free plan first |
| 3 | Data source | Open until phase 0 has been measured on the real host |
| 4 | Where the code lives | Open. Suggested: a `web/` folder in this repository, so it shares the data module |
| 5 | Address | Open. The host's own address first, `insight.themiltonreview.net` later |
| 6 | Student data | Suggested: browser only, no accounts |
| 7 | First release | Suggested: Home and Markets |

## Sources

- [yfinance README](https://github.com/ranaroussi/yfinance) and [yfinance on PyPI](https://pypi.org/project/yfinance/): intended use
- [yfinance discussion 2431](https://github.com/ranaroussi/yfinance/discussions/2431) and [Streamlit forum thread](https://discuss.streamlit.io/t/yfratelimiterror-too-many-requests-rate-limited-try-after-a-while/111207): rate limits on shared cloud addresses
- [Render free plan](https://render.com/free) and [Render compute plans](https://render.com/docs/compute-plans)
- [Cloud Run pricing](https://cloud.google.com/run/pricing) and [Google Cloud free features](https://docs.cloud.google.com/free/docs/free-cloud-features)
- [Railway pricing](https://docs.railway.com/pricing)
- [Hugging Face Spaces overview](https://huggingface.co/docs/hub/en/spaces-overview)
- [GitHub Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits) and [GitHub Actions schedules](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows): for the fallback
- [Cloudflare Workers limits](https://developers.cloudflare.com/workers/platform/limits)

# GTA VI Radar

A local, read-only GTA VI news and discovery dashboard. Collects ten public RSS feeds and optionally searches X for gameplay, vehicles, weapons, missions, discoveries and speculation. Python standard library only. The interface is in English; article titles and source excerpts retain their original language.

## Run locally

Requires Python 3.10 or later on macOS or Linux.

```sh
python3 runner.py
```

Open http://127.0.0.1:8768/. RSS collection starts automatically. Add your own X API Bearer Token through the local configuration form to enable paid X searches. The token is saved in `data/x_bearer` with mode 0600; never commit it.

Optional: set `GTA_RADAR_DATA` to a private directory before starting. Keep the computer on and online. The SQLite database preserves the original 72-hour deadline across restarts. The stop button ends collection; results remain readable.

## Coverage and ranking

- RSS: every 60 seconds after each feed cycle. X: one request every 15 seconds, subject to backoff, budget and deadline.
- Broad discovery query across accounts; excludes replies, retweets and selected promotional terms. It is a sample, not an exhaustive X feed.
- Topic filters, reported findings and speculation/leak views, 100/250/500 items per page.
- X views, likes and reposts are snapshots at ingestion. Missing metrics display N/A. The app does not continually refresh older metrics.
- News score: 75% title-based importance, 25% freshness and rarity in the sample. Meme potential is a title-keyword estimate, not video or image analysis.
- Trend score: 60% logarithmic engagement estimate, 25% importance, 15% similar reports.
- Signal groups compare similar wording within six hours, count distinct X author IDs / publisher domains, and compare publication counts across two 30-minute windows. Different accounts are not proof of independent confirmation. Cross-language matching is limited.
- A multi-source signal requires at least three sources. Source text may include spoilers, false claims or spam.

## Cost controls

An X account with API credits is required. The collector reserves the maximum requested post count before each call and stops X requests at 900 reserved reads (approximately $4.50 at the assumed $0.005/post rate). Verify current provider pricing independently. Failures retain their reservation conservatively; successful responses reconcile to returned post count. Broad collection can exhaust this allowance well before 72 hours. RSS remains free and continues to the deadline.

Configure provider-side spending limits and disable automatic recharge yourself. This repository does not create or fund an X account.

## Security and hosting

This server intentionally binds only to localhost. It is not a public-hosting configuration. Do not expose it to the internet unchanged: its local setup and stop controls are intended for the machine owner. GitHub hosts the source code, not the running collector. Credentials, databases, logs and collected content are excluded from this repository.

## Tests

```sh
python3 -m unittest discover -s tests
```

Tests cover deadline persistence, budget and expiry preventing network calls, cursor pagination, deduplication and reservation handling on request failure.

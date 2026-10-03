# Deployment

TrendFinder has two front-ends that share the same `trendfinder` backend package
(screener, backtester, Jev evaluation):

| Front-end | Entrypoint | Notes |
|---|---|---|
| **Flask** (original) | `app.py` | Full feature set: hover price-chart popup with all ranges, Jev overlay, backtest, evaluate. Uses `gunicorn`. |
| **Streamlit** | `streamlit_app.py` | Built for Streamlit Cloud. Same features, but the ticker chart popup has daily ranges only (`1m/3m/6m/1y`). |

---

## Where the data lives

The app keeps its state in the `data/` directory as plain files:

| File | Purpose | Committed to git? | Survives redeploy? |
|---|---|---|---|
| `data/decisions.db` | Jev decision log (powers the **Evaluate** tab) | No (gitignored) | **No** |
| `data/watchlist.json` | Screener watchlist | Yes (committed) | Container copy resets |
| `data/companies.json` | Company-name cache | No (gitignored) | No |

`data/decisions.db` is a **local SQLite file** created by `trendfinder/decisions.py`
(`DECISIONS_DB = config.DATA_DIR / "decisions.db"`). It is **not** a database server
and is **not** stored in the cloud.

On **Streamlit Cloud**, the repo is cloned into a container and the app creates
`data/decisions.db` in that container's **ephemeral filesystem**. On redeploy or
restart the container is recreated, so the file is **wiped**. The decision log
therefore only accumulates within a single running session.

---

## Deployment options

| Option | Free tier | Persistent `data/`? | Typical cost |
|---|---|---|---|
| **Streamlit Cloud** | Yes (public apps) | No (ephemeral) | **$0** |
| **Render** | Yes (web service, spins down after ~15 min idle) | Needs a paid instance for a persistent disk | **$0** without disk · **~$7/mo** (Starter) with disk |
| **Railway** | $5 one-time trial credit | Yes (volumes) | ~**$5/mo** usage-based |
| **Fly.io** | Small free allowance | Yes (volumes) | ~**$5–10/mo** |

> Prices change; verify on each provider.

### Recommendation

For this app the deciding factor is **persistence of `data/decisions.db`**, which is
what makes the **Evaluate** tab meaningful (it measures forward returns over
~20 trading days).

- **Demo / quick host** → **Streamlit Cloud** (free). The app works fully, but the
  decision log resets on redeploy, so Evaluate never accumulates real history.
- **Full app + working Evaluate** → deploy the **Flask** app to **Render** (or
  Railway/Fly.io) with a **persistent disk mounted at `/app/data`**, and set
  `OPENROUTER_API_KEY` as a secret.
- **Stay on $0 with persistence** → move `decisions.db` to a free hosted Postgres
  (e.g. **Supabase** or **Neon**) so the log survives restarts.

---

## Deploy to Streamlit Cloud

Prereqs: the repo is public, `streamlit_app.py` is at the repo root, and
`requirements.txt` includes `streamlit>=1.32`.

1. Sign in at <https://share.streamlit.io> with the GitHub account that owns the repo.
2. Connect the repo (grant Streamlit Cloud access; easy once it's public).
3. **New app** → select the repo → branch `main`.
4. Set the **main file path** to `streamlit_app.py`.
5. In **Advanced settings → Secrets**, add:
   - `OPENROUTER_API_KEY` (enables the Jev layer; without it Jev is off)
   - optionally `JEV_MODEL`
6. Click **Deploy**.

The `.streamlit/config.toml` hides the Streamlit toolbar/Deploy button and sets the
accent colour for a cleaner deployed app.

---

## Deploy the Flask app to Render

The repo ships a `Dockerfile` and `Procfile` for this.

1. Push the repo to GitHub (public).
2. On Render, **New → Web Service** → connect the repo.
3. Render auto-detects the Dockerfile (or use the `Procfile`: `gunicorn -w 2 -b 0.0.0.0:$PORT app:app`).
4. Add a **persistent disk** and mount it at `/app/data`.
5. Set `OPENROUTER_API_KEY` as an environment variable/secret.

---

## Notes

- Educational only; prices are delayed free data (yfinance). Not investment advice.
- Free yfinance data can be rate-limited; keep the watchlist modest.

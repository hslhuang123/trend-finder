# Deploying TrendFinder

The app ships a **Streamlit** front-end (`streamlit_app.py`) for easy hosting, and
a **Flask** front-end (`app.py`) for the full feature set. Like the stock-agent
app, the easiest host is **Streamlit Community Cloud**, which builds directly from
this GitHub repo, free.

For a full comparison of hosts, costs, and where the data lives, see
**[docs/deployment.md](docs/deployment.md)**.

---

## Option 1 — Streamlit Community Cloud (recommended, same as stock-agent)

1. Go to <https://share.streamlit.io> and sign in with GitHub.
2. **Create app** → **Deploy a public app from GitHub**.
3. Fill in:

   | Field | Value |
   |---|---|
   | Repository | `hslhuang123/trend-finder` |
   | Branch | `main` |
   | Main file path | `streamlit_app.py` |

4. **Advanced settings → Python version: 3.11** (matches `runtime.txt`).
5. Click **Deploy**. The first build takes a few minutes.

Streamlit installs `requirements.txt` automatically.

**Secret (optional but recommended):** the Jev layer needs an OpenRouter key. Add
it under **Manage app → Settings → Secrets**:

```toml
OPENROUTER_API_KEY = "sk-or-v1-..."
```

Without it the app still runs, but the **Jev** judgment and the **Evaluate** tab
stay off/empty.

### Things to know

- Free apps **sleep** after inactivity and wake on the next visit.
- Live data comes from Yahoo (yfinance) and can be rate-limited from a datacenter
  IP; keep the watchlist modest.
- The cloud filesystem is **ephemeral**: the `data/` watchlist, company cache, and
  the `decisions.db` log behind the **Evaluate** tab reset on restart. That is
  expected — they are gitignored. See `docs/deployment.md` for how to persist them
  (hosted DB or a persistent-disk host).

---

## Option 2 — Render / Railway

Both read the committed `Procfile`:

```
web: gunicorn -w 2 -b 0.0.0.0:$PORT app:app
```

- **Render:** New → Web Service → connect the repo → Dockerfile (or build
  `pip install -r requirements.txt` → start `gunicorn -w 2 -b 0.0.0.0:$PORT app:app`).
  Add a **persistent disk** mounted at `/app/data` to keep the decision log.
- **Railway:** New Project → Deploy from GitHub → the `Procfile` is picked up.

---

## Option 3 — Docker (any host)

The committed `Dockerfile` builds a Python 3.11 image and runs `gunicorn app:app`
on port 5000. For Streamlit instead, run:

```bash
streamlit run streamlit_app.py --server.port 8501 --server.address 0.0.0.0
```

---

## Why not GitHub Pages?

GitHub Pages serves only static HTML/CSS/JS. This app computes in Python at
request time (screening, Jev calls, backtests), so it needs a live Python process.
GitHub is the *source*; Streamlit Cloud (or Render/Railway/HF) is the *host*.

# ABDOUUU TEAM VPS — Railway

Railway-ready hosting panel. `main.py` is in the project root; there is no `app/` directory and no Docker dependency.

## Railway
1. Deploy this repository from GitHub.
2. Add Variable: `PANEL_TOKEN` = a strong secret.
3. Recommended: attach a Railway Volume mounted at `/app/data` so projects, sites, logs and SQLite survive redeploys.
4. Railway supplies `PORT` automatically.
5. Open the generated Railway domain.

## Supported uploads
- Bot ZIP: Python (`main.py`, `bot.py`, `app.py`, `index.py`) or Node (`index.js`, `bot.js`, `main.js`, `app.js`), with `requirements.txt` or `package.json` when needed.
- Website ZIP: must contain `index.html`.

Bots run as child processes of the Railway service, with normal network access. This is simpler than Docker but provides less isolation between uploaded bots; use only for trusted uploads.

# Kitsu–AniList Sync Checker

A small Flask web app that compares your Kitsu and AniList anime/manga libraries, shows mismatches (status/progress/missing items), and lets you sync individual entries to keep both sides aligned.

> **Unofficial tool.** This project uses the public AniList GraphQL API and the Kitsu JSON:API but is not affiliated with either service. Use at your own risk.

---

## Why?

Bulk sync tools (for example, MAL‑Sync) are great to get most of your library across, but things can still drift: one platform has an entry the other doesn’t, progress is off by a few episodes/chapters, or the status isn't the same.
**Kitsu–AniList Sync Checker** is meant to run **after** a bulk sync to find and fix those leftovers.

---

## Features

- Compare libraries between **Kitsu** and **AniList**
- Report differences in **status** and **progress**
- Identify entries missing from either platform
- Sync individual entries directly from the report UI
- Works for both **anime** and **manga**

---

## Quickstart

```bash
git clone https://github.com/LordPoc/Kitsu-AniList-Sync-Checker.git
cd Kitsu-AniList-Sync-Checker
python -m venv venv
# macOS / Linux / WSL
source venv/bin/activate
# Windows (PowerShell)
venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env     # or copy manually on Windows
python app.py

# Then open: http://127.0.0.1:5000/
```

Requirements

- Python 3.x
- pip
- AniList account + access token
- Kitsu account (username + password)
- A browser to view the report UI

## Configuration (.env)

Create a `.env` file in the project root (you can copy from `.env.example`):

```
KITSU_USERNAME=your-kitsu-username-or-email
KITSU_PASSWORD=your-kitsu-password
ANILIST_USERNAME=your-anilist-username
ANILIST_ACCESS_TOKEN=your-anilist-token
```

### How to get your AniList access token

1. Open AniList Developer Settings: https://anilist.co/settings/developer
2. Create a new client:
   - Client Name: anything (e.g. Kitsu–AniList Sync Checker)
   - Redirect URL: https://anilist.co/api/v2/oauth/pin
3. Save and copy the Client ID.
4. Visit:

```
https://anilist.co/api/v2/oauth/authorize?client_id=YOUR_CLIENT_ID&response_type=token
```

5. Authorize the client - the redirect URL will contain `#access_token=...`.
6. Paste that token into `.env` as `ANILIST_ACCESS_TOKEN`.


## How to run

Start the Flask application after installing dependencies and configuring `.env`:

```bash
python app.py
```

The app starts a local Flask server (usually at `http://127.0.0.1:5000/`).

## How to use

1. Open the app in your browser.
2. Choose **Anime** or **Manga** to audit.
3. Click **Start Audit** - the app will call both APIs and stream progress to the Logs section.
4. When finished, a Report Summary appears. Click **View Full Report** for item-by-item differences.
5. Use the sync buttons to update progress/status or add missing entries on either platform.

## How it works (overview)

- Fetch Kitsu library using your credentials.
- Fetch AniList library via the GraphQL API.
- Compare items for status, progress, and existence.
- Display a report in the web UI.
- Sync single entries by calling the corresponding API endpoint.

## Notes / Limitations

- This tool is intended to tidy up after a bulk sync tool.
- Keep your `.env` private - it contains account credentials and tokens.
- AniList have rate limits; large libraries may take longer.
- Some entries may not exist on the other platform and must be added manually.

## Troubleshooting

- Nothing loads? Check the terminal running `python app.py` for errors.
- 401 / 403 from AniList? Re-check the token in `.env`.
- Credentials typo? Re-create `.env` from `.env.example`.
- API rate limit? Wait a bit and re-run. AniList exposes rate-limit headers.
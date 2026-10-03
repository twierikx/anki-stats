# Anki-weekrapport

Every Monday morning GitHub Actions downloads a read-only copy of each AnkiWeb
collection, computes last week's stats (reviews, minutes, new cards, % correct,
days studied, streak) and e-mails one Duolingo-style report via Gmail.

## Files

| File | What it does |
|---|---|
| `weekly_report.py` | Entry point: fetch → stats → render → mail |
| `ankiweb_sync.py` | Full *download* from AnkiWeb with the official `anki` package (never uploads) |
| `stats.py` | Weekly numbers from the `revlog` and `cards` tables |
| `report.py` | E-mail HTML + plain-text version |
| `.github/workflows/weekrapport.yml` | Schedule (Mon 07:00 UTC) + manual "Run workflow" |

## Secrets (Settings → Secrets and variables → Actions)

- `ANKI_ACCOUNTS`:
  `[{"name": "Thomas", "username": "ankiweb-login", "password": "…", "email": "…"}, {…}]`
  Put a `\` before any `"` or `\` in a password.
- `SMTP_USER`: the Gmail address that sends the mail
- `SMTP_PASSWORD`: Gmail app password (myaccount.google.com/apppasswords)
- `MAIL_TO` (optional): extra recipients, comma separated

## Testing

Actions → Anki-weekrapport → Run workflow → keep "Alleen testen" ticked. Download
the `weekrapport` artifact and open `weekrapport.html`. Untick it to send a real mail.

Locally, with fake data: `python weekly_report.py --demo`

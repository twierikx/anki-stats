"""Weekly Anki report: download each AnkiWeb collection, compute stats, e-mail them.

Environment variables (GitHub secrets):
  ANKI_ACCOUNTS  JSON list: [{"name", "username", "password", "email"}, ...]
  SMTP_USER      Gmail address that sends the mail
  SMTP_PASSWORD  Gmail app password (16 letters, no spaces)
  MAIL_TO        optional, extra recipients, comma separated

Usage:
  python weekly_report.py              # build and send
  python weekly_report.py --dry-run    # build only, write out/weekrapport.html
  python weekly_report.py --demo       # fake data, no accounts needed (implies --dry-run)
"""

from __future__ import annotations

import argparse
import json
import os
import random
import smtplib
import sys
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

import report
import stats


def parse_accounts(raw: str) -> list[dict]:
    try:
        accounts = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.exit(
            "ANKI_ACCOUNTS is geen geldige JSON "
            f"(regel {exc.lineno}, positie {exc.colno}). Staat er een \\ voor elke \" "
            "of \\ in een wachtwoord?"
        )
    if isinstance(accounts, dict):
        accounts = [accounts]
    for i, acc in enumerate(accounts, 1):
        missing = [k for k in ("name", "username", "password") if not acc.get(k)]
        if missing:
            sys.exit(f"ANKI_ACCOUNTS, account {i}: ontbrekend veld {', '.join(missing)}")
    return accounts


def demo_collection(seed: int, today: date) -> stats.Collection:
    rnd = random.Random(seed)
    revlog = []
    cid = 1
    diligence = 0.9 if seed % 2 else 0.6
    for back in range(120, -1, -1):
        day = today - timedelta(days=back)
        if rnd.random() > diligence:
            continue
        base = datetime(day.year, day.month, day.day, 20, 0, tzinfo=stats.TZ).timestamp()
        for i in range(rnd.randint(15, 90)):
            ts = int((base + i * 9) * 1000)
            if rnd.random() < 0.15:
                revlog.append((ts, cid, 3, 8000, 0))
                cid += 1
            else:
                ease = 1 if rnd.random() < 0.12 else rnd.choice([3, 3, 3, 4, 2])
                revlog.append((ts, rnd.randint(1, max(cid, 2)), ease, rnd.randint(2000, 15000), 1))
    ivls = [rnd.choice([0, 1, 3, 8, 15, 25, 40, 90]) for _ in range(cid + 400)]
    return stats.Collection(revlog=revlog, card_ivls=ivls)


def send(html: str, text: str, subject: str, recipients: list[str]) -> None:
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").replace(" ", "").strip()
    if not user or not password:
        sys.exit("SMTP_USER en/of SMTP_PASSWORD ontbreken in de GitHub secrets.")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"Anki-weekrapport <{user}>"
    msg["To"] = ", ".join(recipients)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        try:
            smtp.login(user, password)
        except smtplib.SMTPAuthenticationError:
            sys.exit(
                "Gmail weigert de login (Username and Password not accepted). "
                "Gebruik een app-wachtwoord in SMTP_PASSWORD, niet je gewone wachtwoord."
            )
        smtp.send_message(msg)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="niet mailen, alleen bestanden maken")
    ap.add_argument("--demo", action="store_true", help="nepgegevens gebruiken")
    ap.add_argument("--week", help="maandag van de week (JJJJ-MM-DD), standaard vorige week")
    ap.add_argument("--out", default="out")
    args = ap.parse_args()
    dry_run = args.dry_run or args.demo

    now = datetime.now(stats.TZ)
    today = (now - timedelta(hours=stats.DEFAULT_ROLLOVER)).date()
    week_start = (
        date.fromisoformat(args.week) if args.week else stats.last_full_week(now.date())
    )

    results: list[stats.WeekStats] = []
    recipients: list[str] = []
    if args.demo:
        for seed, name in ((1, "Thomas"), (2, "Vriendin")):
            results.append(stats.compute(name, demo_collection(seed, today), week_start, today))
    else:
        from ankiweb_sync import AnkiWebError, check_api, download_collection

        print(f"anki-pakket versie {check_api()}", flush=True)

        raw = os.environ.get("ANKI_ACCOUNTS", "").strip()
        if not raw:
            sys.exit("ANKI_ACCOUNTS ontbreekt in de GitHub secrets.")
        for acc in parse_accounts(raw):
            name = acc["name"]
            print(f"Gegevens ophalen voor {name} ...", flush=True)
            try:
                path = download_collection(acc["username"], acc["password"])
                col = stats.load_collection(path)
                results.append(stats.compute(name, col, week_start, today))
                print(f"  {len(col.revlog)} herhalingen in totaal, {len(col.card_ivls)} kaarten")
            except AnkiWebError as exc:
                print(f"::error::Kon de gegevens van {name} niet ophalen: {exc}", flush=True)
                results.append(stats.error_stats(name, week_start, str(exc)))
            if acc.get("email"):
                recipients.append(acc["email"].strip())
        recipients += [m.strip() for m in os.environ.get("MAIL_TO", "").split(",") if m.strip()]
        recipients = list(dict.fromkeys(recipients))

    html = report.render_html(results)
    text = report.render_text(results)
    subject = report.subject(results)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "weekrapport.html").write_text(html, encoding="utf-8")
    (out / "weekrapport.txt").write_text(f"{subject}\n\n{text}", encoding="utf-8")
    print()
    print(subject)
    print(text)

    if all(r.error for r in results):
        sys.exit("Voor geen enkel account konden gegevens worden opgehaald; geen mail verstuurd.")

    if dry_run:
        print(f"Testmodus: niet gemaild. Zie {out / 'weekrapport.html'}")
    else:
        if not recipients:
            recipients = [os.environ.get("SMTP_USER", "")]
        send(html, text, subject, recipients)
        print(f"Gemaild naar: {', '.join(recipients)}")


if __name__ == "__main__":
    main()

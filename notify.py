import math



import smtplib
import ssl
from email.mime.text import MIMEText
from email.utils import formatdate
import os

def send_email(subject: str, body: str, to_email: str, from_email: str):
    """Send a plain-text email via SMTP using credentials from environment. The function reads EMAIL_USER and
    EMAIL_APP_PASSWORD from the environment and performs an SMTP over SSL login to smtp.gmail.com:465 before sending
    the message. Args: subject: Email subject line. body: Plain-text email body. to_email: Recipient email address.
    from_email: Sender email address (used as the envelope sender). Raises: RuntimeError: If EMAIL_USER or
    EMAIL_APP_PASSWORD environment variables are missing. smtplib.SMTPException: Propagates SMTP errors from the
    smtplib calls. Notes: - Credentials are not provided as function arguments intentionally to avoid accidental
    logging; they must be set in the environment. """
    user = os.getenv("EMAIL_USER")
    pwd = os.getenv("EMAIL_APP_PASSWORD")
    if not user or not pwd:
        raise RuntimeError("Missing EMAIL_USER or EMAIL_APP_PASSWORD in .env")

    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Date"] = formatdate(localtime=True)
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(user, pwd)
        server.sendmail(from_email, [to_email], msg.as_string())


def _f2(x):
    try:
        if x is None:
            return "NA"
        xf = float(x)
        if math.isnan(xf) or math.isinf(xf):
            return "NA"
        return f"{xf:.2f}"
    except Exception:
        return "NA"

def compose_report(results: list) -> str:
    lines = ["Fantasy Lock-in Recommendations (tonight)", ""]
    for r in results:
        name = r.get("player", "?")
        if "decision" not in r:
            lines.append(f"- {name}: {r.get('note','no data')}")
            continue

        last_date = r.get("last_game_date", "NA")
        last_fp   = _f2(r.get("last_game_fp"))
        p_lock    = _f2(r.get("p_lock"))
        rarity    = _f2(r.get("rarity_score"))
        rem       = r.get("remaining_games_est", 0)
        decision  = r.get("decision", "WAIT")

        lines.append(f"- {name}: {decision}  (last {last_date} = {last_fp} FP; p_lock={p_lock}, rarity={rarity}, rem={rem})")
    return "\n".join(lines) + "\n"

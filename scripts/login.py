#!/usr/bin/env python3
"""ILIAS-Login über Vercel agent-browser. Schreibt frische Cookies für ilias.py.

Zugangsdaten: Umgebungsvariablen ILIAS_USER und ILIAS_PASSWORD, sonst aus der Datei
.env im Skill-Ordner (eine Zeile KEY=Wert je Variable, chmod 600; Vorlage: .env.example).
Das Skript gibt die Zugangsdaten nie aus. Die ILIAS-Adresse kommt aus config.json
(ilias_url, gesetzt mit `ilias.py setup --url ...`), Standard ist die FH Münster.

  login.py            anmelden (falls nötig), Cookies exportieren, Browser schließen
  login.py --keep     wie oben, Browser bleibt offen: agent-browser --session ilias ...
  login.py --manual   sichtbares Fenster öffnen, der User meldet sich selbst an
  login.py --check    nur prüfen, ob Zugangsdaten hinterlegt sind

Meldungen (erste Zeile der Ausgabe):
  LOGIN OK          Cookies liegen in .cookies.json
  NO CREDENTIALS    ILIAS_USER / ILIAS_PASSWORD fehlen             (Exit 2)
  NETWORK           ILIAS oder der FH-Login antwortet nicht        (Exit 3)
  LOGIN FAILED      Kennung/Passwort abgelehnt, nicht wiederholen  (Exit 4)
  LOGIN STUCK       unbekannte Zwischenseite, z. B. zweiter Faktor (Exit 5)
  MISSING           agent-browser ist nicht installiert            (Exit 6)
"""
import json
import os
import shutil
import subprocess
import sys
import time
from urllib.parse import urlsplit

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = os.path.join(SKILL, ".env")
CONFIG = os.environ.get("ILIAS_SYNC_CONFIG", os.path.join(SKILL, "config.json"))
COOKIES = os.environ.get("COOKIES", os.path.join(SKILL, ".cookies.json"))
DEFAULT_URL = "https://ilias.fh-muenster.de/"
SESSION = "ilias"
PROFILE = "ilias-sync"


def base_url():
    try:
        url = json.load(open(CONFIG, encoding="utf-8")).get("ilias_url")
    except (OSError, ValueError):
        url = None
    return (url or DEFAULT_URL).rstrip("/") + "/"


BASE = base_url()
ILIAS_HOST = urlsplit(BASE).hostname
LOGGED_IN = "!!document.querySelector('a[href*=\"ogout\"]')"          # link „Abmelden“ (doLogout / logout)
HAS_PASSWORD = "!!document.querySelector('input[type=password]')"
SHIBBOLETH = "!!(document.querySelector('#username') && document.querySelector('#password'))"


def stop(code, msg):
    print(msg)
    sys.exit(code)


def ab(*args, stdin=None, check=True, timeout=90):
    """Run one agent-browser command in the ilias session, return parsed JSON data."""
    try:
        r = subprocess.run(["agent-browser", "--session", SESSION, *args, "--json"],
                           input=stdin, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        stop(3, f"NETWORK: agent-browser {args[0]} hat nach {timeout}s nicht geantwortet.")
    try:
        out = json.loads(r.stdout)
    except ValueError:
        out = {"success": False, "error": (r.stderr or r.stdout).strip()[:300]}
    if check and not out.get("success"):
        err = str(out.get("error"))
        if "net::" in err or "ERR_" in err:
            stop(3, f"NETWORK: {err}")
        stop(1, f"ERROR: agent-browser {args[0]}: {err}")
    return out.get("data") or {}


def js(expr):
    return ab("eval", "--stdin", stdin=expr).get("result")


def host():
    return urlsplit(ab("get", "url").get("url", "")).hostname or ""


def credentials():
    vals = {}
    if os.path.exists(ENV):
        if os.stat(ENV).st_mode & 0o077:
            os.chmod(ENV, 0o600)
        for line in open(ENV, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.replace("export ", "").strip(), v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            vals[k] = v
    user = os.environ.get("ILIAS_USER") or vals.get("ILIAS_USER", "")
    pw = os.environ.get("ILIAS_PASSWORD") or vals.get("ILIAS_PASSWORD", "")
    return user, pw


def wait_new_page():
    """Block until the document marked by mark() has been replaced."""
    ab("wait", "--fn", "window.__iliasSync !== 1", check=False, timeout=60)


def mark():
    js("window.__iliasSync = 1")


def logged_in():
    return host() == ILIAS_HOST and bool(js(LOGGED_IN))


def sign_in(user, pw):
    """Fill the login form on the current page (university login server or ILIAS itself)."""
    selectors = []
    if js(SHIBBOLETH):   # standard Shibboleth form; otherwise agent-browser finds the fields itself
        selectors = ["--username-selector", "#username", "--password-selector", "#password"]
        if js("!!document.querySelector('button[name=_eventId_proceed]')"):
            selectors += ["--submit-selector", "button[name=_eventId_proceed]"]
    ab("auth", "save", PROFILE, "--url", f"https://{host()}/", "--username", user,
       "--password-stdin", stdin=pw)
    try:
        mark()
        ab("auth", "login", PROFILE, "--no-navigate", *selectors)
    finally:
        ab("auth", "delete", PROFILE, check=False)   # .env stays the only place with the password
    wait_new_page()
    for _ in range(6):
        if logged_in():
            return
        if js(HAS_PASSWORD):   # the form is back: rejected
            why = js("(document.querySelector('.form-error, .error, [class*=error], .alert')||{}).innerText || ''")
            ab("close", check=False)
            stop(4, f"LOGIN FAILED: Kennung oder Passwort wurden abgelehnt. {str(why).strip()[:200]}")
        if host() != ILIAS_HOST and js("!!document.querySelector('[name=_eventId_proceed]')"):   # consent page
            mark()
            ab("click", "[name=_eventId_proceed]")
            wait_new_page()
            continue
        time.sleep(2)
    u = urlsplit(ab("get", "url").get("url", ""))
    stop(5, f"LOGIN STUCK: Seite „{ab('get', 'title').get('title', '')}“ ({u.hostname}{u.path}). "
            f"Browser bleibt offen: agent-browser --session {SESSION} snapshot -i")


def export_cookies():
    cookies = ab("cookies", "get").get("cookies", [])
    mine = {c["name"]: c["value"] for c in cookies
            if ILIAS_HOST.endswith(c.get("domain", "").lstrip("."))}
    if "PHPSESSID" not in mine:
        stop(1, "ERROR: Der Browser liefert kein ILIAS-Sitzungscookie (PHPSESSID).")
    fd = os.open(COOKIES, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(mine, f)
    return len(mine)


def manual():
    ab("close", check=False)
    subprocess.run(["agent-browser", "--session", SESSION, "--headed", "open", BASE],
                   capture_output=True, text=True, timeout=120)
    print("Fenster ist offen, warte bis zu 5 Minuten auf die Anmeldung …", flush=True)
    end = time.time() + 300
    while time.time() < end:
        if logged_in():
            return
        time.sleep(3)
    stop(4, "LOGIN FAILED: Im Fenster hat sich niemand angemeldet (5 Minuten gewartet).")


def main():
    args = set(sys.argv[1:])
    if args - {"--keep", "--manual", "--check"}:
        stop(1, __doc__)
    user, pw = credentials()
    if "--check" in args:
        if user and pw:
            stop(0, "CREDENTIALS OK: Kennung und Passwort sind hinterlegt.")
        stop(2, f"NO CREDENTIALS: ILIAS_USER/ILIAS_PASSWORD fehlen in {ENV}")
    if not shutil.which("agent-browser"):
        stop(6, "MISSING: npm install -g agent-browser && agent-browser install")

    if "--manual" in args:
        manual()
    else:
        ab("open", BASE)
        if not logged_in() and js(HAS_PASSWORD):
            if not (user and pw):
                ab("close", check=False)
                stop(2, f"NO CREDENTIALS: ILIAS_USER/ILIAS_PASSWORD fehlen in {ENV}")
            sign_in(user, pw)
        if not logged_in():
            ab("open", BASE)
            if not logged_in():
                stop(5, f"LOGIN STUCK: ILIAS zeigt keinen angemeldeten Nutzer. "
                        f"Browser bleibt offen: agent-browser --session {SESSION} snapshot -i")

    n = export_cookies()
    if "--keep" not in args:
        ab("close", check=False)
    print(f"LOGIN OK: {n} Cookies exportiert" + (", Browser bleibt offen" if "--keep" in args else ""))


if __name__ == "__main__":
    main()

#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests", "beautifulsoup4"]
# ///
"""ILIAS -> local semester folder sync.

Run with:  <skill>/scripts/ilias.py <command> ...

Setup (once per machine / semester)
  config                              show the settings, or "SETUP NEEDED" before the first setup
  setup [SEMDIR] [--category TEXT] [--url ILIAS_URL]
                                      save target folder, semester category and ILIAS address
  select SEMDIR [REF=Folder ...] [--ignore REF ...]
                                      choose which courses are synced; ignored ones are never asked again

Sync
  inventory SEMDIR                    what already exists locally (+ manifest summary)
  courses  [--match TEXT | --current] memberships grouped by ILIAS category (semester);
                                      --current = configured category, marks each course and lists NEW ones
  plan     SEMDIR [REF=Folder ...]    crawl the courses (default: all selected ones), write
                                      SEMDIR/.ilias-plan.json, print what is new
  download SEMDIR                     download everything new from the plan (skips known/duplicate files)
  mv       SEMDIR OLD NEW             rename/move a folder inside SEMDIR and remember it for future runs
  dupes    SEMDIR                     list files with identical content

State: <skill>/config.json (settings of this machine), SEMDIR/.ilias-sync.json (manifest: selected and
ignored courses, renamed folders, downloaded files). Cookies come from <skill>/.cookies.json, written
by scripts/login.py (agent-browser).
"""
import hashlib, json, os, re, shutil, sys, tempfile
from urllib.parse import urljoin, unquote, urlsplit

import requests
from bs4 import BeautifulSoup

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.environ.get("ILIAS_SYNC_CONFIG", os.path.join(SKILL, "config.json"))
COOKIES = os.environ.get("COOKIES", os.path.join(SKILL, ".cookies.json"))
DEFAULT_URL = "https://ilias.fh-muenster.de/"


def load_config():
    try:
        return json.load(open(CONFIG, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


BASE = (load_config().get("ilias_url") or DEFAULT_URL).rstrip("/") + "/"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
SKIP_NAMES = {".DS_Store", ".ilias-sync.json", ".ilias-plan.json"}
DATALESS = 0x40000000  # macOS SF_DATALESS (iCloud file not downloaded)
SKIP_DIRS = {".venv", "node_modules", ".git", "__pycache__", ".ipynb_checkpoints"}
TIMEOUT = (10, 60)  # Sekunden für Verbindungsaufbau und Antwort; ohne Grenze hängt der Sync, wenn ILIAS nicht antwortet
NETWORK_HINT = "NETWORK: ILIAS ist nicht erreichbar ({}). Störung bei der Hochschule oder keine Verbindung – später erneut versuchen."


# ---------- helpers ----------
class TimeoutSession(requests.Session):
    def request(self, *args, **kwargs):
        kwargs.setdefault("timeout", TIMEOUT)
        return super().request(*args, **kwargs)


def session():
    s = TimeoutSession()
    if not os.path.exists(COOKIES):
        sys.exit("SESSION EXPIRED: no cookies yet, run scripts/login.py first.")
    s.cookies.update(json.load(open(COOKIES)))
    s.headers["User-Agent"] = UA
    return s


def get_soup(s, url):
    r = s.get(url)
    anon = "nicht in ILIAS eingeloggt" in r.text or "logout" not in r.text.lower()
    elsewhere = urlsplit(r.url).hostname != urlsplit(BASE).hostname   # redirected to the login server
    if anon or elsewhere or "cmd=showLogin" in r.url or "ilstartupgui" in r.url.lower():
        sys.exit("SESSION EXPIRED: run scripts/login.py for fresh cookies, then retry.")
    return BeautifulSoup(r.text, "html.parser")


def clean(seg):
    seg = re.sub(r"\s*\|\s*", " - ", seg)
    return re.sub(r'[/:\\]', "-", seg).strip(" .")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def dataless(path):
    """True for an iCloud placeholder (macOS only; other systems have no st_flags)."""
    return bool(getattr(os.stat(path), "st_flags", 0) & DATALESS)


def walk(root):
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            if fn not in SKIP_NAMES:
                yield os.path.join(dp, fn)


def load_manifest(semdir):
    p = os.path.join(semdir, ".ilias-sync.json")
    m = json.load(open(p)) if os.path.exists(p) else {}
    m.setdefault("courses", {})   # selected: ref -> {folder, renames, title}
    m.setdefault("files", {})     # downloaded: file ref -> path relative to SEMDIR
    m.setdefault("ignored", {})   # deselected: ref -> {title, folder?, renames?}
    return m


def save_manifest(semdir, m):
    json.dump(m, open(os.path.join(semdir, ".ilias-sync.json"), "w"), ensure_ascii=False, indent=1)


def local_path(course, rel_parts):
    """Map an ILIAS path (inside the course) to the local folder, honouring recorded renames."""
    rel = "/".join(rel_parts)
    best = None
    for k in course.get("renames", {}):
        if rel == k or rel.startswith(k + "/"):
            if best is None or len(k) > len(best):
                best = k
    if best is not None:
        rel = (course["renames"][best] + rel[len(best):]).strip("/")
    return os.path.join(course["folder"], rel) if rel else course["folder"]


def fix_name(name, title):
    # ILIAS turns blocked suffixes into ".sec" and glues the old suffix onto the stem: "2.2-1-a1.py" -> "22-1-a1py.sec"
    m = re.match(r".*?(py|sh|js|ts|bat|cmd|php|html?|exe|jar|ps1)\.sec$", name, re.I)
    if m:
        ext = m.group(1).lower()
        t = clean(title)
        return t if t.lower().endswith("." + ext) else f"{t}.{ext}"
    return name


# ---------- commands ----------
def cmd_inventory(semdir):
    m = load_manifest(semdir)
    files = list(walk(semdir)) if os.path.isdir(semdir) else []
    by_top = {}
    for f in files:
        top = os.path.relpath(f, semdir).split(os.sep)[0]
        by_top[top] = by_top.get(top, 0) + 1
    print(f"SEMDIR {semdir} exists={os.path.isdir(semdir)} files={len(files)}")
    for k, v in sorted(by_top.items()):
        print(f"  {k}: {v}")
    print(f"MANIFEST courses={len(m['courses'])} known_files={len(m['files'])}")
    for ref, c in m["courses"].items():
        print(f"  {ref} -> {c['folder']}  renames={c.get('renames', {})}")
    for ref, c in m["ignored"].items():
        print(f"  {ref} ignored  {c.get('title', '')}")


def fetch_courses(match=None):
    """Course memberships as [(category, ref, title)], optionally only categories containing `match`."""
    soup = get_soup(session(), BASE + "ilias.php?baseClass=ilmembershipoverviewgui")
    found = []
    for g in soup.select("div.il-item-group"):
        h = g.find("h3").get_text(strip=True)
        if match and match.lower() not in h.lower():
            continue
        for a in g.select("h4.il-item-title a[href]"):
            hit = re.search(r"/go/crs/(\d+)", a["href"])
            if hit:
                found.append((h, hit.group(1), a.get_text(strip=True)))
    return found


def cmd_courses(match=None, current=False):
    cfg = load_config()
    if current:
        if not cfg.get("category") or not cfg.get("semdir"):
            sys.exit(SETUP_NEEDED)
        match = cfg["category"]
    found = fetch_courses(match)
    m = load_manifest(cfg["semdir"]) if cfg.get("semdir") else None
    mine = (cfg.get("category") or "").lower()
    new, last = [], None
    for cat, ref, title in found:
        if cat != last:
            print(f"## {cat}")
            last = cat
        mark = ""
        if m is not None and mine and mine in cat.lower():
            if ref in m["courses"]:
                mark = f"   [sync -> {m['courses'][ref]['folder']}]"
            elif ref in m["ignored"]:
                mark = "   [ignoriert]"
            else:
                mark = "   [NEU]"
                new.append(ref)
        print(f"  {ref}  {title}{mark}")
    if current:
        here = {ref for _, ref, _ in found}
        for ref, c in m["courses"].items():
            if ref not in here:
                print(f"GONE {ref} ({c['folder']}): nicht mehr unter den Mitgliedschaften des Semesters")
        print(f"NEW {len(new)}" + (": " + " ".join(new) if new else ""))


SETUP_NEEDED = "SETUP NEEDED: Zielordner und Semester sind noch nicht festgelegt (Ersteinrichtung, siehe SKILL.md Schritt 0)."


def cmd_config():
    cfg = load_config()
    if not cfg.get("semdir") or not cfg.get("category"):
        sys.exit(SETUP_NEEDED)
    semdir = cfg["semdir"]
    m = load_manifest(semdir) if os.path.isdir(semdir) else {"courses": {}, "ignored": {}}
    print(f"ILIAS     {BASE}")
    print(f"SEMDIR    {semdir}" + ("" if os.path.isdir(semdir) else "   (Ordner fehlt!)"))
    print(f"CATEGORY  {cfg['category']}")
    print(f"COURSES   {len(m['courses'])} werden synchronisiert, {len(m['ignored'])} abgewählt")
    for ref, c in m["courses"].items():
        print(f"  {ref} -> {c['folder']}" + (f"   ({c['title']})" if c.get("title") else ""))
    for ref, c in m["ignored"].items():
        print(f"  {ref} abgewählt   ({c.get('title', '')})")
    if not m["courses"]:
        print("NO COURSES: noch keine Kurse ausgewählt (select).")


def cmd_setup(args):
    cfg = load_config()
    i = 0
    while i < len(args):
        if args[i] in ("--category", "--url") and i + 1 < len(args):
            cfg["category" if args[i] == "--category" else "ilias_url"] = args[i + 1].strip()
            i += 2
        elif not args[i].startswith("--") and i == 0:
            cfg["semdir"] = os.path.abspath(os.path.expanduser(args[i]))
            os.makedirs(cfg["semdir"], exist_ok=True)
            i += 1
        else:
            sys.exit(__doc__)
    if cfg.get("ilias_url"):
        if not cfg["ilias_url"].startswith("http"):
            sys.exit("--url needs the full address, e.g. https://ilias.example.org/")
        cfg["ilias_url"] = cfg["ilias_url"].rstrip("/") + "/"
    json.dump(cfg, open(CONFIG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for k in ("ilias_url", "semdir", "category"):
        print(f"{k}: {cfg.get(k) or ('(Standard) ' + DEFAULT_URL if k == 'ilias_url' else '(offen)')}")


def cmd_select(semdir, args):
    """Add courses (REF=Folder) and/or deselect them (--ignore REF ...). Files on disk are never touched."""
    m = load_manifest(semdir)
    try:
        titles = {ref: title for _, ref, title in fetch_courses()}
    except SystemExit:   # no valid session: selection still works, only the titles are missing
        titles = {}
    ignore = False
    for a in args:
        if a == "--ignore":
            ignore = True
        elif ignore:
            if not a.isdigit():
                sys.exit(f"--ignore expects course refs, got: {a}")
            old = m["courses"].pop(a, {})
            entry = {**m["ignored"].get(a, {}), **old}
            entry["title"] = titles.get(a) or entry.get("title", "")
            m["ignored"][a] = entry
            print(f"ignored  {a}  {entry['title']}")
        else:
            ref, _, folder = a.partition("=")
            folder = folder.strip().strip("/")
            if not ref.isdigit() or not folder:
                sys.exit(f"expected REF=Folder, got: {a}")
            back = m["ignored"].pop(ref, {})
            if ref in m["courses"]:
                if m["courses"][ref]["folder"] != folder:
                    sys.exit(f"{ref} is already synced to '{m['courses'][ref]['folder']}'. Rename folders with: mv")
            elif back.get("folder") == folder:   # re-selected: keep the remembered renames
                m["courses"][ref] = {"folder": folder, "renames": back.get("renames", {})}
            else:
                m["courses"][ref] = {"folder": folder, "renames": {}}
            if titles.get(ref) or back.get("title"):
                m["courses"][ref]["title"] = titles.get(ref) or back["title"]
            print(f"sync     {ref} -> {folder}  {m['courses'][ref].get('title', '')}")
    os.makedirs(semdir, exist_ok=True)
    save_manifest(semdir, m)
    print(f"{len(m['courses'])} courses synced, {len(m['ignored'])} ignored")


def crawl(s, url, path, out, seen):
    soup = get_soup(s, url)
    col = soup.find(id="il_center_col") or soup
    for a in col.select("a.il_ContainerItemTitle"):
        h = urljoin(BASE, a["href"])
        title = a.get_text(strip=True)
        m = re.search(r"/go/(\w+)/(\d+)", h) or re.search(r"cmdClass=(\w+).*?ref_id=(\d+)|ref_id=(\d+).*?cmdClass=(\w+)", h)
        if "sendfile" in h:
            kind, ref = "file", re.search(r"ref_id=(\d+)", h).group(1)
        elif m and m.re.pattern.startswith("/go"):
            kind, ref = m.group(1), m.group(2)
        else:
            ref = (re.search(r"ref_id=(\d+)", h) or [None, None])[1]
            cls = (re.search(r"cmdClass=(\w+)", h) or [None, ""])[1].lower()
            base = (re.search(r"baseClass=(\w+)", h) or [None, ""])[1].lower()
            kind = "tst" if "test" in cls else {"ilobjfoldergui": "fold", "ilobjgroupgui": "grp", "ilobjexercisegui": "exc"}.get(cls) or (
                "webr" if "linkresource" in base or "linkresource" in cls else cls or base or "?")
        if (kind, ref) in seen:
            continue
        seen.add((kind, ref))
        if kind == "file":
            out["files"].append({"ref": ref, "title": title, "path": path, "url": h})
        elif kind in ("fold", "grp"):
            crawl(s, h, path + [clean(title)], out, seen)
        else:
            item = {"kind": kind, "ref": ref, "title": title, "path": path, "url": h}
            if kind == "webr" and ref:
                r = s.get(f"{BASE}ilias.php?baseClass=illinkresourcehandlergui&cmdNode=j3:q7&cmdClass=ilObjLinkResourceGUI&cmd=calldirectlink&ref_id={ref}", allow_redirects=False)
                item["target"] = r.headers.get("Location")
            out["other"].append(item)


def cmd_plan(semdir, pairs):
    s = session()
    m = load_manifest(semdir)
    for p in pairs:
        ref, folder = p.split("=", 1)
        m["courses"].setdefault(ref, {"folder": folder, "renames": {}})
        m["ignored"].pop(ref, None)
    refs = [p.split("=", 1)[0] for p in pairs] or list(m["courses"])
    if not refs:
        sys.exit("NO COURSES: nothing selected yet. Choose courses first: select SEMDIR REF=Folder ...")
    plan = {}
    for ref in refs:
        out = {"files": [], "other": []}
        crawl(s, f"{BASE}go/crs/{ref}", [], out, {("crs", ref)})
        plan[ref] = out
        course = m["courses"][ref]
        new = [f for f in out["files"] if f["ref"] not in m["files"]]
        print(f"## {course['folder']} (crs {ref}): {len(out['files'])} files, {len(new)} not yet known, {len(out['other'])} other items")
        for f in new:
            print(f"   + {local_path(course, f['path'])}/{f['title']}")
        for o in out["other"]:
            print(f"   ~ [{o['kind']}] {'/'.join(o['path'])} :: {o['title']} {o.get('target') or ''}")
    save_manifest(semdir, m)
    json.dump(plan, open(os.path.join(semdir, ".ilias-plan.json"), "w"), ensure_ascii=False, indent=1)


def cmd_download(semdir):
    s = session()
    m = load_manifest(semdir)
    plan = json.load(open(os.path.join(semdir, ".ilias-plan.json")))
    # index existing files once: (name,size) and lazily their hashes
    existing = list(walk(semdir))
    by_name_size = {(os.path.basename(f), os.path.getsize(f)): f for f in existing}
    hashes = {}

    def hash_index():
        if not hashes:
            for f in existing:
                if dataless(f):  # iCloud placeholder: reading would force a download
                    continue
                try:
                    hashes.setdefault(sha256(f), f)
                except OSError:
                    pass
        return hashes

    stats = {"new": 0, "known": 0, "same_name_size": 0, "dup_content": 0, "fail": 0}
    for ref, out in plan.items():
        course = m["courses"][ref]
        for f in out["files"]:
            known = m["files"].get(f["ref"])
            if known and os.path.exists(os.path.join(semdir, known)):
                stats["known"] += 1
                continue
            tmp = None
            try:
                r = s.get(f["url"], stream=True)
                if r.status_code != 200 or "text/html" in r.headers.get("Content-Type", ""):
                    print(f"FAIL {f['title']} ({r.status_code})")
                    stats["fail"] += 1
                    continue
                cd = r.headers.get("Content-Disposition", "")
                mm = re.search(r"filename\*=UTF-8''([^;]+)", cd) or re.search(r'filename="?([^";]+)"?', cd)
                name = fix_name(clean(unquote(mm.group(1))) if mm else clean(f["title"]), f["title"])
                size = int(r.headers.get("Content-Length") or -1)
                hit = by_name_size.get((name, size))
                if hit:
                    r.close()
                    m["files"][f["ref"]] = os.path.relpath(hit, semdir)
                    stats["same_name_size"] += 1
                    continue
                tmp = tempfile.NamedTemporaryFile(delete=False, dir=semdir, prefix=".dl-")
                for ch in r.iter_content(1 << 16):
                    tmp.write(ch)
                tmp.close()
                os.chmod(tmp.name, 0o644)
                digest = sha256(tmp.name)
                cdir = os.path.join(semdir, course["folder"])
                # iCloud placeholders cannot be hashed without downloading them; same size in the same course counts as duplicate
                ph = [e for e in existing if e.startswith(cdir + os.sep) and dataless(e) and os.path.getsize(e) == os.path.getsize(tmp.name)]
                if ph:
                    os.unlink(tmp.name)
                    m["files"][f["ref"]] = os.path.relpath(ph[0], semdir)
                    stats["dup_content"] += 1
                    continue
                if digest in hash_index():
                    os.unlink(tmp.name)
                    m["files"][f["ref"]] = os.path.relpath(hashes[digest], semdir)
                    stats["dup_content"] += 1
                    continue
                folder = os.path.join(semdir, local_path(course, f["path"]))
                os.makedirs(folder, exist_ok=True)
                dest = os.path.join(folder, name)
                if os.path.exists(dest):  # same name, different content: keep both
                    b, e = os.path.splitext(dest)
                    i = 2
                    while os.path.exists(f"{b} ({i}){e}"):
                        i += 1
                    dest = f"{b} ({i}){e}"
                shutil.move(tmp.name, dest)
                hashes[digest] = dest
                by_name_size[(name, size)] = dest
                m["files"][f["ref"]] = os.path.relpath(dest, semdir)
                stats["new"] += 1
                print(f"NEW {os.path.relpath(dest, semdir)}")
            except requests.RequestException as e:  # Zeitlimit oder Abbruch: Datei als FAIL zählen, weitermachen
                if tmp is not None and os.path.exists(tmp.name):
                    os.unlink(tmp.name)
                print(f"FAIL {f['title']} ({type(e).__name__})")
                stats["fail"] += 1
        save_manifest(semdir, m)
    print("STATS", stats)


def cmd_mv(semdir, old, new):
    m = load_manifest(semdir)
    old, new = old.strip("/"), new.strip("/")
    src, dst = os.path.join(semdir, old), os.path.join(semdir, new)
    if not os.path.exists(src):
        sys.exit(f"missing: {src}")
    # move / merge on disk
    if os.path.isdir(dst) and os.path.isdir(src):
        for child in os.listdir(src):
            if os.path.exists(os.path.join(dst, child)):
                sys.exit(f"conflict: {new}/{child} exists")
        for child in os.listdir(src):
            shutil.move(os.path.join(src, child), os.path.join(dst, child))
        os.rmdir(src)
    else:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.exists(dst):
            sys.exit(f"conflict: {new} exists")
        shutil.move(src, dst)
    # remember it
    otop, ntop = old.split("/")[0], new.split("/")[0]
    for c in m["courses"].values():
        if c["folder"] != otop:
            continue
        if "/" not in old:  # course folder renamed
            c["folder"] = new
        else:
            orel, nrel = old.split("/", 1)[1], (new.split("/", 1)[1] if "/" in new else "")
            if ntop != otop:
                sys.exit("moving between courses is not supported")
            hit = [k for k, v in c["renames"].items() if v == orel or v.startswith(orel + "/")]
            for k in hit:
                c["renames"][k] = (nrel + c["renames"][k][len(orel):]).strip("/")
            if not any(c["renames"][k] == nrel for k in hit):
                c["renames"][orel] = nrel
    for ref, p in m["files"].items():
        if p == old or p.startswith(old + "/"):
            m["files"][ref] = new + p[len(old):]
    save_manifest(semdir, m)
    print(f"moved {old} -> {new}")


def cmd_dupes(semdir):
    seen = {}
    for f in walk(semdir):
        if dataless(f):
            continue
        seen.setdefault((os.path.getsize(f), sha256(f)), []).append(os.path.relpath(f, semdir))
    groups = [v for v in seen.values() if len(v) > 1]
    for g in groups:
        print("DUP:", " | ".join(g))
    print(f"{len(groups)} duplicate groups")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    c = a[0]
    try:
        if c == "inventory": cmd_inventory(a[1])
        elif c == "config": cmd_config()
        elif c == "setup": cmd_setup(a[1:])
        elif c == "select": cmd_select(a[1], a[2:])
        elif c == "courses": cmd_courses(a[2] if len(a) > 2 and a[1] == "--match" else None, current="--current" in a)
        elif c == "plan": cmd_plan(a[1], a[2:])
        elif c == "download": cmd_download(a[1])
        elif c == "mv": cmd_mv(a[1], a[2], a[3])
        elif c == "dupes": cmd_dupes(a[1])
        else: sys.exit(__doc__)
    except (requests.ConnectionError, requests.Timeout) as e:
        sys.exit(NETWORK_HINT.format(type(e).__name__))

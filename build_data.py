#!/usr/bin/env python3
"""Build data.js from real Claude session logs + Chrome history.

Usage:
    python3 build_data.py            # defaults: May 2026, Australia/Sydney
    python3 build_data.py 2026 5

Outputs data.js next to this script (overwrites). Run with Chrome closed if
possible — otherwise the script copies the locked DB to a temp file first.
"""
from __future__ import annotations
import json, os, re, sqlite3, sys, shutil, tempfile, calendar
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from collections import defaultdict

TZ = ZoneInfo("Australia/Sydney")
DAY_START_HR = 6  # logical day = 06:00 → 06:00 next day

# Load .env (KEY=value lines) sitting next to this script, if present.
def _load_dotenv():
    p = Path(__file__).with_name(".env")
    if not p.exists(): return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        # don't overwrite an env var already set in the shell
        os.environ.setdefault(k, v)
_load_dotenv()
HOME = Path.home()
CLAUDE_DIR = HOME / ".claude" / "projects"
CHROME_DB  = HOME / "Library/Application Support/Google/Chrome/Default/History"
VSCODE_HIST = HOME / "Library/Application Support/Code/User/History"
KNOWLEDGE_DB = HOME / "Library/Application Support/Knowledge/knowledgeC.db"
REPO_ROOTS = [HOME / "Documents/MQ/repo", HOME / "Documents/notes"]  # tweak if needed
OUT = Path(__file__).with_name("data.js")
SNAPSHOTS_FILE = Path(__file__).with_name("snapshots.json")  # all stored days in one file
LLM_CACHE = Path(__file__).with_name("domain_cats.json")  # cached LLM verdicts
VALID_CATS = {"research", "coding", "writing", "meeting", "admin", "personal"}

# ── categorization ────────────────────────────────────────────────────────────
RESEARCH = ["arxiv.org", "scholar.google", "huggingface.co", "openreview",
            "paperswithcode", "semanticscholar", "acm.org", "ieee.org",
            "aclanthology", "neurips.cc", "researchgate", "nature.com",
            "biorxiv", "ssrn.com",
            "adaren100.github.io"]  # Ada's own blog / notes
CODING   = ["github.com", "stackoverflow.com", "pytorch.org", "tensorflow.org",
            "docs.python.org", "claude.ai", "anthropic.com", "kaggle.com",
            "wandb.ai", "colab.research.google.com", "ollama", "vscode", "npmjs",
            "pypi.org", "readthedocs.io", "developer.mozilla", "gitlab.com",
            "stackoverflow", "openrouter.ai", "console.anthropic", "platform.openai",
            "modal.com", "replicate.com", "supabase", "vercel", "render.com",
            "huggingface.co/spaces"]
WRITING  = ["overleaf.com", "docs.google.com", "notion.so", "hackmd.io",
            "obsidian", "sharelatex", "typora", "grammarly", "quillbot",
            "drive.google.com"]
ADMIN    = ["mail.google.com", "calendar.google.com", "slack.com",
            "outlook.live", "outlook.office", "discord.com",
            "doodle.com", "trello.com", "asana", "linear.app", "jira"]
MEETING  = ["zoom.us", "meet.google.com", "teams.microsoft", "webex.com",
            "whereby.com", "around.co", "around.us"]

# ── LLM categorization for unknown domains (cached on disk) ───────────────────
def _static_categorize(url: str):
    """Pure keyword lookup; returns category or None."""
    u = url.lower()
    for kw in MEETING:
        if kw in u: return "meeting"
    for kw in RESEARCH:
        if kw in u: return "research"
    for kw in CODING:
        if kw in u: return "coding"
    for kw in WRITING:
        if kw in u: return "writing"
    for kw in ADMIN:
        if kw in u: return "admin"
    return None

def _load_llm_cache():
    if LLM_CACHE.exists():
        try: return json.loads(LLM_CACHE.read_text())
        except Exception: pass
    return {}

def _save_llm_cache(c):
    LLM_CACHE.write_text(json.dumps(c, indent=2, sort_keys=True))

def llm_categorize(unknown_domains, model="claude-haiku-4-5-20251001"):
    """Ask Claude to bucket unknown domains. Returns {domain: cat}."""
    if not unknown_domains: return {}
    try:
        import anthropic
    except ImportError:
        print("[warn] anthropic SDK not installed; skipping LLM categorization. "
              "`pip install anthropic` and set ANTHROPIC_API_KEY to enable.",
              file=sys.stderr)
        return {}
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[warn] ANTHROPIC_API_KEY not set; skipping LLM categorization.", file=sys.stderr)
        return {}
    client = anthropic.Anthropic()
    out = {}
    BATCH = 60
    rules = (
        "Bucket each domain into ONE of: research, coding, writing, meeting, admin, personal.\n"
        "  research = reading academic papers, ML/AI articles, technical blog posts, news ABOUT ML/AI/science\n"
        "  coding   = dev tools, GitHub-like, package docs, cloud consoles\n"
        "  writing  = doc editors (Overleaf/Docs/Notion), note-taking\n"
        "  meeting  = video conferencing tools (Zoom/Meet/Teams)\n"
        "  admin    = email, calendar, chat (Slack/Discord), bank, university admin\n"
        "  personal = entertainment, social media, shopping, news (non-research), random scrolling\n"
        "Reply with ONLY valid JSON: a single object mapping each domain → one category. No prose."
    )
    for i in range(0, len(unknown_domains), BATCH):
        batch = unknown_domains[i:i+BATCH]
        msg = "Domains:\n" + "\n".join(batch)
        try:
            resp = client.messages.create(
                model=model, max_tokens=2048,
                system=rules,
                messages=[{"role": "user", "content": msg}],
            )
            text = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
            # strip code fences if Claude wrapped the JSON
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
            verdict = json.loads(text)
            for d, c in verdict.items():
                if c in VALID_CATS: out[d] = c
            print(f"[llm] categorized {len(verdict)}/{len(batch)} (batch {i//BATCH + 1})", file=sys.stderr)
        except Exception as ex:
            print(f"[warn] LLM batch failed: {ex}", file=sys.stderr)
    return out

def build_url_categorizer(all_urls):
    """Returns a categorize(url) function that uses keywords first, then LLM cache."""
    cache = _load_llm_cache()
    # collect domains needing LLM verdict (not statically matched, not in cache)
    unknown = sorted({
        domain(u) for u in all_urls
        if _static_categorize(u) is None and domain(u) not in cache
    })
    if unknown:
        print(f"[info] {len(unknown)} unknown domains → asking Claude", file=sys.stderr)
        verdicts = llm_categorize(unknown)
        cache.update(verdicts)
        if verdicts: _save_llm_cache(cache)
    def cat_of(url):
        c = _static_categorize(url)
        if c: return c
        return cache.get(domain(url), "personal")
    return cat_of

def categorize(url: str) -> str:
    u = url.lower()
    for kw in MEETING:
        if kw in u: return "meeting"
    for kw in RESEARCH:
        if kw in u: return "research"
    for kw in CODING:
        if kw in u: return "coding"
    for kw in WRITING:
        if kw in u: return "writing"
    for kw in ADMIN:
        if kw in u: return "admin"
    return "personal"

def domain(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url)
    return m.group(1).replace("www.", "") if m else url[:40]

# ── Chrome history ────────────────────────────────────────────────────────────
def read_chrome(start_utc: datetime, end_utc: datetime):
    """Returns list of (datetime_local, url, title)."""
    if not CHROME_DB.exists():
        print("[warn] Chrome history not found, skipping", file=sys.stderr)
        return []
    # Copy to temp so a running Chrome can't block us
    tmp = Path(tempfile.mkdtemp()) / "History"
    shutil.copy2(CHROME_DB, tmp)
    # Chrome time = microseconds since 1601-01-01 UTC
    EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)
    s = int((start_utc - EPOCH).total_seconds() * 1_000_000)
    e = int((end_utc   - EPOCH).total_seconds() * 1_000_000)
    rows = []
    try:
        con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
        # Only this device: exclude visits that have a row in visit_source
        # (those are synced from other devices or imported from other browsers).
        cur = con.execute(
            "SELECT visits.visit_time, urls.url, urls.title FROM visits "
            "JOIN urls ON urls.id = visits.url "
            "WHERE visits.visit_time BETWEEN ? AND ? "
            "AND visits.id NOT IN (SELECT id FROM visit_source) "
            "ORDER BY visits.visit_time", (s, e))
        for vt, url, title in cur:
            dt_utc = EPOCH + timedelta(microseconds=vt)
            rows.append((dt_utc.astimezone(TZ), url, title or domain(url)))
        con.close()
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)
    return rows

# ── Claude sessions ───────────────────────────────────────────────────────────
def _is_scheduled(obj):
    """A session is scheduled iff it contains a queue-operation entry — that's
    only present for cron-fired runs. Mentioning <scheduled-task> in chat doesn't
    count, so interactive sessions about scheduled-task files are preserved."""
    return obj.get("type") == "queue-operation"

def read_claude(start_utc: datetime, end_utc: datetime):
    """Returns list of (datetime_local, session_id, project_short, title).
    Filters out sessions that were triggered by a scheduled task."""
    rows = []
    if not CLAUDE_DIR.exists():
        return rows
    # First pass: figure out which session IDs are scheduled-task runs
    scheduled_sids = set()
    files = []
    for proj_dir in CLAUDE_DIR.iterdir():
        if not proj_dir.is_dir(): continue
        short = proj_dir.name.split("-")[-1] or proj_dir.name
        for jf in proj_dir.glob("*.jsonl"):
            files.append((proj_dir, short, jf))
            try:
                with jf.open() as f:
                    for line in f:
                        try:
                            obj = json.loads(line)
                        except Exception:
                            continue
                        if _is_scheduled(obj):
                            sid = obj.get("sessionId") or jf.stem
                            scheduled_sids.add(sid)
            except Exception as ex:
                print(f"[warn] scan {jf}: {ex}", file=sys.stderr)
    print(f"[info] excluded scheduled sessions: {len(scheduled_sids)}", file=sys.stderr)
    # Second pass: collect events from non-scheduled sessions only
    for proj_dir, short, jf in files:
        try:
            with jf.open() as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    ts = obj.get("timestamp")
                    if not ts: continue
                    try:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except Exception:
                        continue
                    if dt < start_utc or dt > end_utc: continue
                    sid = obj.get("sessionId") or jf.stem
                    if sid in scheduled_sids: continue
                    if obj.get("type") == "queue-operation": continue
                    rows.append((dt.astimezone(TZ), sid, short, "Claude session · " + short))
        except Exception as ex:
            print(f"[warn] skip {jf}: {ex}", file=sys.stderr)
    return rows

# ── VS Code edit history ──────────────────────────────────────────────────────
WRITING_EXT = {".tex", ".md", ".bib", ".typ", ".rst", ".txt"}
CODING_EXT  = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".c", ".cpp",
               ".h", ".hpp", ".java", ".rb", ".php", ".cs", ".swift", ".kt",
               ".sh", ".zsh", ".sql", ".yaml", ".yml", ".json", ".toml",
               ".html", ".css", ".scss", ".vue", ".lua", ".r", ".ipynb"}

def _cat_from_resource(uri: str):
    """Categorize a VS Code resource URI by extension / scheme."""
    u = uri.lower()
    # Overleaf VS Code extension → writing, regardless of ext
    if u.startswith("overleaf-workshop://"):
        return "writing"
    ext = os.path.splitext(u.split("?")[0])[1]
    if ext in WRITING_EXT: return "writing"
    if ext in CODING_EXT:  return "coding"
    return None  # skip unknown

def read_vscode(start_utc: datetime, end_utc: datetime):
    """Returns list of (datetime_local, resource_uri, category, title)."""
    rows = []
    if not VSCODE_HIST.exists(): return rows
    start_ms = int(start_utc.timestamp() * 1000)
    end_ms   = int(end_utc.timestamp()   * 1000)
    for sub in VSCODE_HIST.iterdir():
        ej = sub / "entries.json"
        if not ej.exists(): continue
        try:
            data = json.loads(ej.read_text())
        except Exception:
            continue
        res = data.get("resource", "")
        cat = _cat_from_resource(res)
        if cat is None: continue
        # short title from the URI's file name
        name = res.split("?")[0].rstrip("/").rsplit("/", 1)[-1] or res
        for e in data.get("entries", []):
            ts = e.get("timestamp")
            if not isinstance(ts, (int, float)): continue
            if ts < start_ms or ts > end_ms: continue
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).astimezone(TZ)
            rows.append((dt, res, cat, name))
    return rows

# ── repo file mtimes (fallback for editors other than VS Code) ────────────────
SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__",
             "dist", "build", ".next", ".cache", ".idea", ".vscode"}

def read_repo_mtimes(start_utc: datetime, end_utc: datetime):
    """Returns list of (datetime_local, path, category, name)."""
    rows = []
    start_ts = start_utc.timestamp()
    end_ts   = end_utc.timestamp()
    seen = set()
    for root in REPO_ROOTS:
        if not root.exists(): continue
        for dirpath, dirnames, files in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for fn in files:
                ext = os.path.splitext(fn)[1].lower()
                if ext in WRITING_EXT: cat = "writing"
                elif ext in CODING_EXT: cat = "coding"
                else: continue
                p = os.path.join(dirpath, fn)
                try: mt = os.path.getmtime(p)
                except OSError: continue
                if mt < start_ts or mt > end_ts: continue
                key = (round(mt), fn)
                if key in seen: continue
                seen.add(key)
                dt = datetime.fromtimestamp(mt, tz=timezone.utc).astimezone(TZ)
                rows.append((dt, p, cat, fn))
    return rows

# ── knowledgeC.db: per-app focus events ───────────────────────────────────────
# Each row is a *real* focus span (start, end) — no dwell guessing needed.
BUNDLE_CAT = {
    # coding
    "com.microsoft.VSCode": "coding",
    "com.microsoft.VSCodeInsiders": "coding",
    "com.microsoft.VSCode-Insiders": "coding",
    "com.todesktop.230313mzl4w4u92": "coding",   # Cursor
    "com.exafunction.windsurf": "coding",
    "com.apple.dt.Xcode": "coding",
    "com.apple.Terminal": "coding",
    "com.googlecode.iterm2": "coding",
    "co.zeit.hyper": "coding",
    "com.github.atom": "coding",
    "com.sublimetext.4": "coding",
    "com.jetbrains.pycharm": "coding",
    "com.jetbrains.intellij": "coding",
    "com.jetbrains.WebStorm": "coding",
    "com.openai.codex": "coding",                # Codex.app
    "com.anthropic.claudefordesktop": "coding",  # Claude Desktop
    "com.google.antigravity": "coding",          # Google Antigravity IDE
    "com.todesktop.240716u3u1yy41w": "coding",   # another ToDesktop IDE (likely Cursor variant)
    "com.microsoft.Excel": "admin",
    # writing
    "md.obsidian": "writing",
    "obsidian.md": "writing",
    "abnerworks.Typora": "writing",
    "com.literatureandlatte.scrivener": "writing",
    "com.microsoft.Word": "writing",
    "com.apple.iWork.Pages": "writing",
    "com.apple.TextEdit": "writing",
    "com.figma.Desktop": "writing",
    # research / reading
    "com.apple.Preview": "research",             # PDFs
    "com.readdle.PDFExpert-Mac": "research",
    "org.zotero.zotero": "research",             # Zotero
    # admin / comms
    "com.tinyspeck.slackmacgap": "admin",
    "com.hnc.Discord": "admin",
    "com.microsoft.Outlook": "admin",
    "com.apple.mail": "admin",
    "us.zoom.xos": "meeting",
    "com.microsoft.teams2": "meeting",
    "com.cisco.webex.meetings": "meeting",
    "com.apple.iCal": "admin",
    # personal
    "com.spotify.client": "personal",
    "com.apple.Music": "personal",
    "com.netflix.Netflix": "personal",
    "com.apple.MobileSMS": "personal",
    "net.whatsapp.WhatsApp": "personal",
    "com.tencent.xinWeChat": "personal",
}
# Browsers are handled by Chrome history (richer signal with URLs).
SKIP_BUNDLES = {
    "com.google.Chrome", "com.apple.Safari", "org.mozilla.firefox",
    "company.thebrowser.Browser", "com.brave.Browser",
    "com.microsoft.edgemac", "com.operasoftware.Opera", "com.arc.browser",
    "com.apple.Spotlight", "com.apple.dock", "com.apple.finder",
    "com.apple.systempreferences", "com.apple.WindowManager", "loginwindow",
}

def read_knowledgec(start_utc, end_utc):
    """Returns event dicts straight from /app/inFocus spans."""
    if not KNOWLEDGE_DB.exists():
        print("[info] knowledgeC.db not found — skipping macOS focus", file=sys.stderr)
        return []
    tmp = Path(tempfile.mkdtemp()) / "knowledgeC.db"
    try:
        shutil.copy2(KNOWLEDGE_DB, tmp)
    except PermissionError:
        print("[warn] knowledgeC.db unreadable — grant Full Disk Access to Terminal "
              "in System Settings → Privacy & Security → Full Disk Access", file=sys.stderr)
        return []
    COCOA = datetime(2001, 1, 1, tzinfo=timezone.utc)
    s = (start_utc - COCOA).total_seconds()
    e = (end_utc   - COCOA).total_seconds()
    # Merge adjacent same-bundle spans (gap ≤ MERGE_GAP) before filtering, so
    # fragmented focus events (e.g. Zotero page flips) aren't dropped as blips.
    MERGE_GAP = 120  # seconds
    raw = []
    try:
        con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
        cur = con.execute(
            "SELECT ZVALUESTRING, ZSTARTDATE, ZENDDATE FROM ZOBJECT "
            "WHERE ZSTREAMNAME = '/app/usage' "
            "AND ZSTARTDATE BETWEEN ? AND ? ORDER BY ZSTARTDATE", (s, e))
        for bundle, sd, ed in cur:
            if not bundle or sd is None or ed is None: continue
            if bundle in SKIP_BUNDLES: continue
            cat = BUNDLE_CAT.get(bundle)
            if cat is None: continue
            raw.append((bundle, cat, sd, ed))
        con.close()
        merged = []
        for bundle, cat, sd, ed in raw:
            if merged and merged[-1][0] == bundle and sd - merged[-1][3] <= MERGE_GAP:
                merged[-1][3] = max(merged[-1][3], ed)
                merged[-1][4] += 1
            else:
                merged.append([bundle, cat, sd, ed, 1])
        out = []
        for bundle, cat, sd, ed, hits in merged:
            if ed - sd < 60: continue
            st  = (COCOA + timedelta(seconds=sd)).astimezone(TZ)
            en  = (COCOA + timedelta(seconds=ed)).astimezone(TZ)
            short = bundle.split(".")[-1]
            out.append({"start": st, "end": en, "cat": cat, "src": "macos",
                        "title": short, "note": bundle, "hits": hits})
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)
    return out

# ── dwell-aware bucketing (Chrome) ────────────────────────────────────────────
def chrome_to_events(rows, max_dwell_min=20, gap_min=5, cat_fn=None):
    """Each Chrome visit spans [t, t + min(gap_to_next_visit, max_dwell_min)].
    Then merge adjacent same-category spans whose gap <= gap_min."""
    if not rows: return []
    if cat_fn is None: cat_fn = categorize
    rows = sorted(rows, key=lambda r: r[0])
    spans = []
    for i, (dt, url, title) in enumerate(rows):
        cat = cat_fn(url)
        if cat is None: continue
        if i + 1 < len(rows):
            gap = (rows[i + 1][0] - dt).total_seconds() / 60
            dwell = min(gap, max_dwell_min) if gap > 0 else max_dwell_min
        else:
            dwell = 3  # final visit of the window: short tail
        if dwell < 0.5: continue
        end = dt + timedelta(minutes=dwell)
        spans.append({"start": dt, "end": end, "cat": cat,
                      "title": (title or domain(url))[:60], "src": "chrome",
                      "hits": 1, "note": domain(url)})
    # merge same-category adjacent spans
    out = []
    for s in spans:
        if out and s["cat"] == out[-1]["cat"] and (s["start"] - out[-1]["end"]).total_seconds() <= gap_min * 60:
            out[-1]["end"] = max(out[-1]["end"], s["end"])
            out[-1]["hits"] += 1
            # keep the longer / earlier title
            if len(s["title"]) > len(out[-1]["title"]): out[-1]["title"] = s["title"]
        else:
            out.append(dict(s))
    # drop tiny events
    return [e for e in out if (e["end"] - e["start"]).total_seconds() / 60 >= MIN_DUR]

# ── bucketing into events ─────────────────────────────────────────────────────
GAP_MIN = 5    # default gap (minutes) > this ends a run
MIN_DUR = 2    # drop events shorter than this
TAIL_MIN = 3   # default dwell after the last hit in a run

def to_events(items, cat_of, title_of, src, gap_min=None, tail_min=None):
    """items: list of (dt_local, key, *extras). cat_of(item) -> category. title_of(item) -> str."""
    if not items: return []
    g = GAP_MIN if gap_min is None else gap_min
    t = TAIL_MIN if tail_min is None else tail_min
    items = sorted(items, key=lambda x: x[0])
    events = []
    cur = None  # (start, last, cat, title, src)
    for it in items:
        dt = it[0]
        cat = cat_of(it)
        if cat is None: continue
        title = title_of(it)
        if cur and cat == cur["cat"] and (dt - cur["last"]).total_seconds() <= g * 60:
            cur["last"] = dt
            cur["hits"] += 1
            # keep first non-empty title; otherwise overwrite with most recent
            if not cur["title"] or len(cur["title"]) < 6:
                cur["title"] = title
        else:
            if cur: events.append(cur)
            cur = {"start": dt, "last": dt, "cat": cat, "title": title, "src": src, "hits": 1}
    if cur: events.append(cur)
    out = []
    for e in events:
        end = e["last"] + timedelta(minutes=t)
        dur = (end - e["start"]).total_seconds() / 60
        if dur < MIN_DUR: continue
        out.append({
            "start": e["start"],
            "end":   end,
            "cat":   e["cat"],
            "src":   e["src"],
            "title": e["title"][:60],
            "note":  f"{e['hits']} hit{'s' if e['hits']!=1 else ''}",
        })
    return out

def logical_day(dt):
    """Calendar date of the LOGICAL day this datetime belongs to (day starts at DAY_START_HR)."""
    if dt.hour < DAY_START_HR:
        dt = dt - timedelta(days=1)
    return dt.date()

# Lower number = wins overlap. More specific sources (URL, file) beat coarse ones.
SOURCE_PRIORITY = {"macos": 1, "vscode": 2, "claude": 3, "chrome": 4, "local": 5}

def dedupe_overlap(evts):
    """Resolve overlapping events into non-overlapping segments. For each slice
    of time covered by multiple events, the highest-priority source wins."""
    if not evts: return []
    evts = [{**e, "_pri": SOURCE_PRIORITY.get(e["src"], 99)} for e in evts]
    # Collect all timepoint boundaries
    pts = sorted({e["start"] for e in evts} | {e["end"] for e in evts})
    out = []
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        if (b - a).total_seconds() < 30:  # skip sub-30-second slivers
            continue
        # events covering [a, b)
        covering = [e for e in evts if e["start"] <= a and e["end"] >= b]
        if not covering: continue
        winner = min(covering, key=lambda e: e["_pri"])
        seg = {k: v for k, v in winner.items() if k != "_pri"}
        seg["start"], seg["end"] = a, b
        # merge with previous if same category and contiguous
        if out and out[-1]["cat"] == seg["cat"] and out[-1]["end"] == a:
            out[-1]["end"] = b
        else:
            out.append(seg)
    return out

def split_at_day_boundary(evts):
    """Split any event that crosses the logical-day boundary (DAY_START_HR)."""
    out = []
    for e in evts:
        s, en = e["start"], e["end"]
        while logical_day(s) != logical_day(en):
            # boundary = 06:00 of (logical_day(s) + 1 day)
            ld = logical_day(s)
            boundary = datetime(ld.year, ld.month, ld.day, DAY_START_HR, 0, tzinfo=s.tzinfo) + timedelta(days=1)
            out.append({**e, "start": s, "end": boundary - timedelta(seconds=1)})
            s = boundary
        out.append({**e, "start": s, "end": en})
    return out

def merge_events(all_evts):
    """Merge across sources: if two adjacent same-cat events overlap or are <2 min apart, merge."""
    all_evts.sort(key=lambda e: e["start"])
    out = []
    for e in all_evts:
        if out and e["cat"] == out[-1]["cat"] and (e["start"] - out[-1]["end"]).total_seconds() <= 120:
            out[-1]["end"] = max(out[-1]["end"], e["end"])
            out[-1]["note"] = f"merged"
        else:
            out.append(dict(e))
    return out

# ── build per-day ─────────────────────────────────────────────────────────────
REAL = {"research", "coding", "writing", "meeting"}

def fmt_clock(dt):  return dt.strftime("%H:%M")
def fmt_dur(mins):
    mins = int(round(mins))
    h, m = divmod(mins, 60)
    return f"{h}h {m}m" if h and m else f"{h}h" if h else f"{m}m"

DOW       = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]
DOW_LONG  = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"]
MONTHS    = ["January","February","March","April","May","June",
             "July","August","September","October","November","December"]

def build_day(year, month, dnum, events):
    py_dow = datetime(year, month, dnum).weekday()  # Mon=0..Sun=6
    dow = (py_dow + 1) % 7                          # to JS Sun=0..Sat=6
    weekend = dow in (0, 6)
    # day bounds: actual first→last event, or default 09–17 if empty
    if events:
        day_start = min(e["start"] for e in events)
        day_end   = max(e["end"]   for e in events)
    else:
        day_start = datetime(year, month, dnum, 9, 0, tzinfo=TZ)
        day_end   = datetime(year, month, dnum, 17, 0, tzinfo=TZ)
    logged = real = 0
    longest = run = 0
    cs = 0
    last_cat = None
    j1mt = 0
    for i, e in enumerate(events):
        d = (e["end"] - e["start"]).total_seconds() / 60
        logged += d
        if e["cat"] in REAL:
            real += d
            run += d
            longest = max(longest, run)
        else:
            run = 0
        if last_cat and e["cat"] != last_cat: cs += 1
        last_cat = e["cat"]
    # "just one more thing": short leak (<10m) sandwiched by real-work
    for i in range(1, len(events) - 1):
        e = events[i]
        d = (e["end"] - e["start"]).total_seconds() / 60
        if e["cat"] in REAL or d >= 10: continue
        if events[i-1]["cat"] in REAL and events[i+1]["cat"] in REAL:
            j1mt += 1
    chrome_count = sum(1 for e in events if e["src"] == "chrome")
    tabs_opened = chrome_count * 3
    return {
        "key": f"{year}-{month}-{dnum}",
        "dayNum": dnum, "dow": dow, "weekend": weekend,
        "dateShort": f"{DOW[dow]}, {MONTHS[month-1][:3]} {dnum}",
        "dateLong":  f"{DOW_LONG[dow]}, {MONTHS[month-1]} {dnum}",
        "dayStart":  fmt_clock(day_start),
        "dayEnd":    fmt_clock(day_end),
        "events": [{
            "start": fmt_clock(e["start"]),
            "end":   fmt_clock(e["end"]),
            "cat":   e["cat"], "src": e["src"],
            "title": e["title"], "note": e["note"],
        } for e in events],
        "logged": int(round(logged)),
        "real":   int(round(real)),
        "deep":   int(round(real)),
        "ratio":  (real / logged) if logged else 0,
        "stats": {
            "contextSwitches": cs,
            "tabsOpened":      tabs_opened,
            "longestFocus":    fmt_dur(longest) if longest else "0m",
            "justOneMoreThing": j1mt,
        },
    }

# ── per-day storage: one JSON file, keyed "YYYY-MM-DD" ────────────────────────
def _snap_key(year, month, dnum):
    return f"{year}-{month:02d}-{dnum:02d}"

def load_all_snapshots():
    if SNAPSHOTS_FILE.exists():
        try: return json.loads(SNAPSHOTS_FILE.read_text())
        except Exception: pass
    return {}

def save_all_snapshots(store):
    SNAPSHOTS_FILE.write_text(json.dumps(store, indent=2, ensure_ascii=False, sort_keys=True))

def compute_events(start_local, end_local):
    """Read every source for the window, return a deduped event list."""
    start_utc = start_local.astimezone(timezone.utc)
    end_utc   = end_local.astimezone(timezone.utc)

    chrome_rows = read_chrome(start_utc, end_utc)
    claude_rows = read_claude(start_utc, end_utc)
    vscode_rows = read_vscode(start_utc, end_utc)
    mtime_rows  = read_repo_mtimes(start_utc, end_utc)
    macos_evts  = read_knowledgec(start_utc, end_utc)
    print(f"[info] chrome: {len(chrome_rows)}  claude: {len(claude_rows)}  "
          f"vscode: {len(vscode_rows)}  mtimes: {len(mtime_rows)}  "
          f"macos-focus: {len(macos_evts)}", file=sys.stderr)

    cat_fn = build_url_categorizer([r[1] for r in chrome_rows])
    chrome_evts = chrome_to_events(chrome_rows, max_dwell_min=20, gap_min=5, cat_fn=cat_fn)
    claude_evts = to_events(claude_rows,
        cat_of=lambda r: "coding",
        title_of=lambda r: r[3], src="claude")
    vscode_evts = to_events(vscode_rows,
        cat_of=lambda r: r[2],
        title_of=lambda r: "VS Code · " + r[3],
        src="vscode", gap_min=20, tail_min=5)
    mtime_evts = to_events(mtime_rows,
        cat_of=lambda r: r[2],
        title_of=lambda r: r[3],
        src="local", gap_min=20, tail_min=5)
    return split_at_day_boundary(
        dedupe_overlap(chrome_evts + claude_evts + vscode_evts + mtime_evts + macos_evts)
    )

# ── main ──────────────────────────────────────────────────────────────────────
def main(year=2026, month=5, force=False):
    """Compute only days without snapshots (+ today, since it's in progress).
    Reuse stored snapshots for past days. Pass force=True to recompute everything."""
    today = datetime.now(TZ).date()
    days_in = calendar.monthrange(year, month)[1]
    target_days = list(range(1, days_in + 1))

    # Decide which days need computing
    store = {} if force else load_all_snapshots()
    need_compute = []
    snapshots = {}
    for d in target_days:
        date = datetime(year, month, d).date()
        snap = store.get(_snap_key(year, month, d))
        if snap is not None and date < today:
            snapshots[d] = snap   # historical + already stored → immutable
        else:
            need_compute.append(d)

    if need_compute:
        first, last = min(need_compute), max(need_compute)
        start_local = datetime(year, month, first, DAY_START_HR, 0, tzinfo=TZ)
        end_local   = datetime(year, month, last,  DAY_START_HR, 0, tzinfo=TZ) + timedelta(days=1)
        print(f"[info] computing {len(need_compute)} day(s) of {year}-{month:02d} "
              f"({first}–{last}); {len(snapshots)} loaded from snapshots", file=sys.stderr)
        all_evts = compute_events(start_local, end_local)
        by_day = defaultdict(list)
        for e in all_evts:
            by_day[logical_day(e["start"]).day].append(e)
        saved = 0
        for d in need_compute:
            day_dict = build_day(year, month, d, by_day.get(d, []))
            snapshots[d] = day_dict
            date = datetime(year, month, d).date()
            if date < today:
                store[_snap_key(year, month, d)] = day_dict
                saved += 1
        if saved:
            save_all_snapshots(store)
            print(f"[saved] {saved} day(s) → {SNAPSHOTS_FILE.name}", file=sys.stderr)
    else:
        print(f"[info] all {len(target_days)} day(s) loaded from snapshots — no compute needed", file=sys.stderr)

    days = [snapshots[d] for d in target_days]
    target_month_dict = _make_month_payload(year, month, days)

    # Bundle EVERY month that has at least one stored day, so the widget can
    # switch months without re-running the build.
    full_store = load_all_snapshots()
    # Merge in the just-computed target month (in case nothing was saved yet)
    for d in target_days:
        full_store[_snap_key(year, month, d)] = snapshots[d]
    months_by_ym = defaultdict(list)
    for key, day in full_store.items():
        ym = key[:7]  # "YYYY-MM"
        months_by_ym[ym].append((int(key.split('-')[2]), day))
    months_payload = {}
    for ym, items in months_by_ym.items():
        y, mo = int(ym[:4]), int(ym[5:7])
        days_in_mo = calendar.monthrange(y, mo)[1]
        by_d = {n: d for n, d in items}
        # Fill in missing days with empty placeholders so calendar layout stays valid
        full_days = []
        for d in range(1, days_in_mo + 1):
            if d in by_d:
                full_days.append(by_d[d])
            else:
                full_days.append(build_day(y, mo, d, []))
        months_payload[ym] = _make_month_payload(y, mo, full_days)
    default_key = f"{year}-{month:02d}"

    body_default = json.dumps(target_month_dict, ensure_ascii=False, indent=2)
    body_months  = json.dumps(months_payload, ensure_ascii=False, indent=2)
    js = (
        "/* Built from real Claude sessions + Chrome history. "
        f"Source: build_data.py · TZ: Australia/Sydney · {datetime.now(TZ).isoformat(timespec='seconds')} */\n"
        "(function () {\n"
        "  window.WL_REAL = [\"research\", \"coding\", \"writing\", \"meeting\"];\n"
        f"  window.WORKLOG_MONTHS = {body_months};\n"
        f"  window.WORKLOG_DEFAULT_MONTH = \"{default_key}\";\n"
        f"  window.WORKLOG_MONTH = {body_default};\n"  # back-compat: single-month consumers
        "})();\n"
    )
    OUT.write_text(js)
    print(f"[ok] wrote {OUT} ({len(js):,} bytes) — {len(months_payload)} month(s)", file=sys.stderr)

def _make_month_payload(year, month, days):
    return {
        "month": f"{MONTHS[month-1]} {year}",
        "year":  year, "monthIndex": month - 1,
        "key":   f"{year}-{month:02d}",
        "cats": {
            "research": {"label": "Reading",       "short": "reading", "color": "#3f9d6f"},
            "coding":   {"label": "Coding",        "short": "coding",  "color": "#3b6fa0"},
            "writing":  {"label": "Writing",       "short": "writing", "color": "#2f8e8a"},
            "meeting":  {"label": "Meeting",       "short": "meeting", "color": "#7b6cd9"},
            "admin":    {"label": "Slacking",      "short": "admin",   "color": "#d99a3c"},
            "personal": {"label": "Doomscrolling", "short": "scroll",  "color": "#cf5670"},
        },
        "days": days,
    }

if __name__ == "__main__":
    force = "--force" in sys.argv
    _now = datetime.now(TZ)
    main(_now.year, _now.month, force=force)

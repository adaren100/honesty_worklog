# Honest Worklog

How does a PhD survive? Where does the day actually go?
I don't know — so I let the laptop tell me.

This is an honest worklog: no self-reporting, no manual tagging.
It reads Chrome history and macOS focus events straight off this machine,
buckets each minute into one of six categories, and shows me the result.

**Live demo:** <https://adaren100.github.io/worklog/>

## How it categorizes

Everything I do on this laptop falls into one of six buckets —
**Reading, Coding, Writing, Meeting, Slacking, Doomscrolling**.
Here's exactly which apps go where:

- **Reading** — Apple Preview, PDF Expert, Zotero
- **Coding** — VS Code, VS Code Insiders, Cursor, Windsurf, Xcode, Terminal, iTerm2, Hyper, Atom, Sublime Text, PyCharm, IntelliJ, WebStorm, Codex.app, Claude Desktop, Google Antigravity
- **Writing** — Obsidian, Typora, Scrivener, Microsoft Word, Apple Pages, TextEdit, Figma
- **Meeting** — Zoom, Microsoft Teams, Cisco Webex
- **Slacking** — Slack, Discord, Outlook, Apple Mail, Apple Calendar, Microsoft Excel
- **Doomscrolling** — Spotify, Apple Music, Netflix, Messages, WhatsApp, WeChat
- **Ignored** — all browsers (Chrome / Safari / Firefox / Arc / Brave / Edge / Opera / Dia), Spotlight, Dock, Finder, System Settings, WindowManager, loginwindow

## How it measures time

- **Chrome**: each visit lasts `min(gap to next visit, 20 min)` — the cap stops a forgotten tab from looking like 8 hours of reading.
- **macOS focus**: real `(start, end)` spans from `knowledgeC.db`; same-app spans within 120s merge, sub-60s blips drop.
- **VS Code / file edits**: timestamps cluster into runs (split after 20-min gaps), each run gets a 5-min tail.
- Events under 2 minutes are dropped from every source.
- **Overlap dedupe**: when sources overlap, priority order is `macos > vscode > claude > chrome > local`. Chrome loses because an open tab ≠ time spent there.
- Adjacent same-category events within 5 minutes merge into one block.
- A "day" runs 06:00 → 06:00; events crossing midnight split at the boundary.
- Scheduled cron Claude sessions are excluded (not me working).

## Files

- `build_data.py` — pulls activity from `~/.claude/projects`, Chrome history,
  VS Code edit history, and macOS `knowledgeC.db`; categorises domains
  (static rules + LLM fallback); writes `data.js`.
- `Honest Worklog.html` — entry page; loads `data.js` and the widgets below.
- `widget.jsx` — day view.
- `month.jsx` — month overview.
- `tweaks-panel.jsx` — inline editor for categories / events.
- `data.js` — generated; example month included so the widget renders out of
  the box.

## Run

```bash
cp .env.example .env
python3 build_data.py
python3 -m http.server 1314
open http://localhost:1314/Honest%20Worklog.html
```

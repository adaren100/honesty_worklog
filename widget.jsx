// worklog/widget.jsx — the honest worklog widget
const { useState, useMemo, useEffect, useRef } = React;

/* ---------- helpers ---------- */
const toMin = (hhmm) => { const [h, m] = hhmm.split(":").map(Number); return h * 60 + m; };
const fmtDur = (min) => {
  const h = Math.floor(min / 60), m = min % 60;
  return h ? (m ? `${h}h ${m}m` : `${h}h`) : `${m}m`;
};
const fmtClock = (hhmm) => {
  let [h, m] = hhmm.split(":").map(Number);
  const ap = h >= 12 ? "pm" : "am"; const hh = ((h + 11) % 12) + 1;
  return `${hh}:${String(m).padStart(2, "0")}${ap}`;
};

/* tone-dependent sublines */
const SUBLINES = {
  savage:  "You were “busy” for ten hours. The work fit in two.",
  deadpan: "Logged: a full day. Shipped: one bug fix from this morning.",
  gentle:  "Heavy day. Two real hours of work is still two real hours.",
};
const VERDICT_TAG = { savage: "questionable", deadpan: "as expected", gentle: "we move" };

/* ---------- source badge ---------- */
function Src({ src }) {
  const isClaude = src === "claude";
  return (
    <span className="wl-src" style={{ color: isClaude ? "var(--ink)" : "var(--muted)" }}>
      {isClaude ? "✦ Claude" : "◷ Chrome"}
    </span>
  );
}

/* ---------- timeline ---------- */
function Timeline({ events, cats, span, t0, active, setActive }) {
  const total = span;
  const [hover, setHover] = useState(null);
  // wrap times that fall before t0 into the [t0, t0+span) range
  const wrap = (m) => (m < t0 ? m + 24 * 60 : m);

  // hour ticks — every 3h across the 24h span starting at t0
  const step = span >= 18 * 60 ? 3 : 1;
  const ticks = [];
  for (let off = 0; off <= span; off += step * 60) {
    const left = (off / total) * 100;
    const hh = (Math.floor((t0 + off) / 60)) % 24;
    const lab = hh === 0 ? "12a" : hh === 12 ? "12p" : hh < 12 ? hh + "a" : (hh - 12) + "p";
    ticks.push({ left, lab });
  }

  return (
    <div className="wl-timeline">
      <div className="wl-band" onMouseLeave={() => setHover(null)}>
        <div className="wl-segs">
          {events.map((e, i) => {
            const s = wrap(toMin(e.start)), eMin = wrap(toMin(e.end));
            const left = ((s - t0) / total) * 100;
            const w = ((eMin - s) / total) * 100;
            const dim = active && active !== e.cat;
            const isHover = hover === i;
            return (
              <div
                key={i}
                className={"wl-seg" + (isHover ? " is-hover" : "")}
                style={{ position: "absolute", left: left + "%", width: w + "%", background: cats[e.cat].color, opacity: dim ? 0.16 : 1 }}
                onMouseEnter={() => setHover(i)}
              />
            );
          })}
        </div>
        {hover != null && <Tooltip e={events[hover]} t0={t0} total={total} cats={cats} />}
      </div>
      <div className="wl-ticks">
        {ticks.map((tk, i) => (
          <span key={i} className="wl-tick" style={{ left: tk.left + "%" }}>{tk.lab}</span>
        ))}
      </div>
    </div>
  );
}

function Tooltip({ e, t0, total, cats }) {
  // center over the segment's actual time position (with logical-day wrap)
  const wrap = (m) => (m < t0 ? m + 24 * 60 : m);
  const s = wrap(toMin(e.start)), eMin = wrap(toMin(e.end));
  const left = ((s - t0) / total) * 100;
  const w = ((eMin - s) / total) * 100;
  const center = left + w / 2;
  return (
    <div className="wl-tip" style={{ left: `clamp(120px, ${center}%, calc(100% - 120px))` }}>
      <div className="wl-tip-head">
        <span className="wl-dot" style={{ background: cats[e.cat].color }} />
        <span className="wl-tip-time">{fmtClock(e.start)}–{fmtClock(e.end)}</span>
        <span className="wl-tip-dur">{fmtDur(((toMin(e.end) - toMin(e.start)) + 1440) % 1440)}</span>
      </div>
      <div className="wl-tip-title">{e.src === "claude" ? "Claude session" : (e.note || "—")}</div>
      <div className="wl-tip-foot"><Src src={e.src} /></div>
    </div>
  );
}

/* ---------- breakdown: overall split + per-category activity drill-down ---------- */
function Leaks({ events, cats, total, active, setActive }) {
  const rows = useMemo(() => {
    const g = {};
    // seed every main category so 0m rows still render in the breakdown
    Object.keys(cats).forEach((k) => { g[k] = { k, min: 0, items: [] }; });
    events.forEach((e) => {
      let d = toMin(e.end) - toMin(e.start);
      if (d < 0) d += 1440; // event crossed midnight
      (g[e.cat] = g[e.cat] || { k: e.cat, min: 0, items: [] });
      g[e.cat].min += d;
      g[e.cat].items.push({ ...e, dur: d });
    });
    Object.values(g).forEach((x) => x.items.sort((a, b) => b.dur - a.dur));
    return Object.values(g)
      .map((x) => ({ ...x, ...cats[x.k] }))
      .sort((a, b) => b.min - a.min);
  }, [events, cats]);
  const max = Math.max(1, ...rows.map((r) => r.min));

  return (
    <div className="wl-leaks">
      {rows.map((r) => {
        const open = active === r.k;
        const dim = active && !open;
        const empty = r.min === 0;
        return (
          <div key={r.k} className={"wl-leak-group" + (open ? " is-open" : "") + (empty ? " is-empty" : "")} style={{ opacity: dim ? 0.4 : empty ? 0.55 : 1 }}>
            <button
              className={"wl-leak" + (open ? " is-active" : "")}
              onClick={() => !empty && setActive(open ? null : r.k)}
              aria-expanded={open}
              disabled={empty}
            >
              <span className="wl-leak-name">
                <span className="wl-dot" style={{ background: r.color }} />
                {r.label}
              </span>
              <span className="wl-bar-track">
                <span className="wl-bar-fill" style={{ width: (r.min / max * 100) + "%", background: r.color }} />
              </span>
              <span className="wl-leak-dur">{empty ? "—" : fmtDur(r.min)}</span>
              <span className="wl-chev" style={empty ? { opacity: 0 } : null}>›</span>
            </button>
            {open && (
              <div className="wl-leak-detail" style={{ borderColor: r.color }}>
                <div className="wl-act-cap">
                  {r.items.length} {r.items.length === 1 ? "session" : "sessions"} · {(window.WL_REAL || []).includes(r.k) ? "what actually got done" : "where it actually went"}
                </div>
                {r.items.map((it, i) => (
                  <div className="wl-act" key={i}>
                    <span className="wl-act-time">{fmtClock(it.start)}</span>
                    <span className="wl-act-title">{it.src === "claude" ? "Claude session" : (it.note || "—")}</span>
                    <span className="wl-act-src">{it.src === "claude" ? "✦" : "◷"}</span>
                    <span className="wl-act-dur">{fmtDur(it.dur)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ---------- footer stats ---------- */
function Stats({ s }) {
  const items = [
    [s.contextSwitches, "context switches"],
    [s.tabsOpened, "tabs opened"],
    [s.longestFocus, "best focus streak"],
    [s.justOneMoreThing, "“just one more thing”s"],
  ];
  return (
    <div className="wl-stats">
      {items.map(([v, l], i) => (
        <span key={i} className="wl-stat"><b>{v}</b> {l}</span>
      ))}
    </div>
  );
}

/* day verdict subline: scales with how little real work happened */
function daySubline(tone, ratio) {
  if (tone === "deadpan") return "Logged: a full day. Advanced: the email backlog.";
  if (tone === "gentle") return "Heavy day. A couple of real hours still counts.";
  // savage, ratio-aware
  if (ratio < 0.18) return "A full day logged. The thesis did not move.";
  if (ratio < 0.32) return "Plenty of motion. Research, coding and writing got the scraps.";
  return "Not a bad day. Don’t let it get to your head.";
}

window.DayView = function DayView({ day, tone = "savage", showStats = true, cats, onPrev, onNext, hasPrev, hasNext }) {
  const C = cats || (window.WORKLOG_MONTH && window.WORKLOG_MONTH.cats);
  // logical day: 06:00 → 06:00 next morning (late-night work stays on the same day)
  const t0 = 6 * 60, span = 24 * 60;
  const [active, setActive] = useState(null);
  useEffect(() => { setActive(null); }, [day.key]);

  return (
    <div className="wl-body">
      <div className="wl-daterow">
        <div className="wl-datenav">
          <button className="wl-arrow" onClick={onPrev} disabled={!hasPrev} aria-label="Previous day">‹</button>
          <span className="wl-date">{day.dateLong}</span>
          <button className="wl-arrow" onClick={onNext} disabled={!hasNext} aria-label="Next day">›</button>
        </div>
      </div>

      <div className="wl-verdict">
        <span className="wl-v1">{fmtDur(day.logged)} logged.</span>
        <span className="wl-v2">{fmtDur(day.real)} was <em>reading, coding, or writing</em>.</span>
      </div>

      <Timeline events={day.events} cats={C} span={span} t0={t0} active={active} setActive={setActive} />

      <div className="wl-leak-head"><span className="wl-leak-title">Where the time went</span> <span className="wl-hint">tap to expand</span></div>
      <div className="wl-leak-scroll">
        <Leaks events={day.events} cats={C} total={span} active={active} setActive={setActive} />
      </div>

      {showStats && <Stats s={day.stats} />}
    </div>
  );
};

Object.assign(window, { toMin, fmtDur, fmtClock, SUBLINES, VERDICT_TAG, Leaks, Stats });

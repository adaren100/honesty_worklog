// worklog/month.jsx — month view: a calendar navigator into daily logs
(function () {
  function hexToRgb(hex) {
    const h = hex.replace("#", "");
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
  }
  const rgba = (hex, a) => { const [r, g, b] = hexToRgb(hex); return `rgba(${r},${g},${b},${a})`; };

  // monthly calendar heat color — “Sage · soft green”, tiles tinted by share of real work
  const HEAT = "#4f9b76";

  /* aggregate one day's events: category sums + top leak (for pips + hover only) */
  function aggDay(day) {
    const sums = {};
    day.events.forEach((e) => { sums[e.cat] = (sums[e.cat] || 0) + (window.toMin(e.end) - window.toMin(e.start)); });
    let leak = null, leakV = -1;
    const REAL = window.WL_REAL || ["research", "coding", "writing"];
    Object.keys(sums).forEach((k) => { if (!REAL.includes(k) && sums[k] > leakV) { leakV = sums[k]; leak = k; } });
    if (!leak) leak = Object.keys(sums).sort((a, b) => sums[b] - sums[a])[0];
    return { sums, leak };
  }

  function Calendar({ M, cats, onSelectDay, heat }) {
    const HC = heat || (cats && cats.research && cats.research.color) || HEAT;
    const col = (dow) => (dow + 6) % 7; // Mon=0 … Sun=6
    // arrange days into Mon–Sun week rows
    const rows = [];
    let row = [], first = true;
    M.days.forEach((d, idx) => {
      if (first) { for (let i = 0; i < col(d.dow); i++) row.push(null); first = false; }
      row.push({ d, idx });
      if (col(d.dow) === 6) { rows.push(row); row = []; }
    });
    if (row.length) rows.push(row);
    const headers = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

    return (
      <div className="wl-cal">
        <div className="wl-cal-head">
          {headers.map((h) => <span key={h} className="wl-cal-dow">{h}</span>)}
        </div>
        {rows.map((wk, ri) => (
          <div className="wl-cal-week" key={ri}>
            {headers.map((_, ci) => {
              const cell = wk[ci];
              if (!cell) return <span className="wl-cal-empty" key={ci} />;
              const { d, idx } = cell;
              const a = aggDay(d);
              const leakCat = a.leak && cats[a.leak] ? cats[a.leak] : null;
              const tint = rgba(HC, 0.07 + d.ratio * 0.9);
              return (
                <button key={ci} className={"wl-cal-cell" + (d.weekend ? " is-weekend" : "")} style={{ background: tint }}
                  onClick={() => onSelectDay(idx)}>
                  <span className="wl-cal-num">{d.dayNum}</span>
                  <span className="wl-cal-figs">
                    <span className="wl-cal-real">{d.logged ? window.fmtDur(d.logged) : "—"}</span>
                    <span className="wl-cal-focus">{d.real ? window.fmtDur(d.real) + " real" : "no real work"}</span>
                  </span>
                  <span className="wl-cal-tip">
                    <span className="wl-tip-head">
                      <span className="wl-tip-time">{d.dateShort}</span>
                      <span className="wl-tip-dur">{window.fmtDur(d.logged)}</span>
                    </span>
                    <span className="wl-cal-tip-row"><b>{window.fmtDur(d.real)}</b> real work</span>
                    <span className="wl-cal-tip-row"><b>{d.stats && d.stats.longestFocus ? d.stats.longestFocus : "0m"}</b> longest focus</span>
                    {leakCat ? (
                      <span className="wl-cal-tip-row wl-cal-tip-leak">
                        <span className="wl-dot" style={{ background: leakCat.color }} />
                        mostly {leakCat.label.toLowerCase()}
                      </span>
                    ) : (
                      <span className="wl-cal-tip-row wl-cal-tip-leak">no activity logged</span>
                    )}
                  </span>
                </button>
              );
            })}
          </div>
        ))}
      </div>
    );
  }

  const INTRO = {
    savage:  "Pick a day. Watch it slip away in fast-forward.",
    deadpan: "Each square is a day. Click one for the damage.",
    gentle:  "Pick any day to revisit how it really went.",
  };

  window.MonthView = function MonthView({ M, tone = "savage", cats, onSelectDay, heat,
                                          onPrevMonth, onNextMonth, hasPrevMonth, hasNextMonth }) {
    const C = cats || M.cats;
    const HC = heat || (C && C.research && C.research.color) || HEAT;
    return (
      <div className="wl-body">
        <div className="wl-daterow">
          <div className="wl-datenav">
            <button className="wl-arrow" onClick={onPrevMonth} disabled={!hasPrevMonth} aria-label="Previous month">‹</button>
            <span className="wl-date">{M.month}</span>
            <button className="wl-arrow" onClick={onNextMonth} disabled={!hasNextMonth} aria-label="Next month">›</button>
          </div>
          <span className="wl-tag">{M.days.length} days</span>
        </div>

        <p className="wl-month-intro">{INTRO[tone] || INTRO.savage}</p>

        <Calendar M={M} cats={C} onSelectDay={onSelectDay} heat={HC} />

        <div className="wl-cal-scale">
          <span>less</span>
          <span className="wl-cal-grad" style={{ background: `linear-gradient(90deg, ${rgba(HC, 0.12)}, ${rgba(HC, 1)})` }} />
          <span>more real work</span>
          <span className="wl-cal-hint">click a day to open it</span>
        </div>
      </div>
    );
  };
  // expose for the color-options comparison page
  window.WL_Calendar = Calendar;
})();

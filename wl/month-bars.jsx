// worklog/month-bars.jsx — month view as a strip of daily stacked bars.
// Bar height = hours at the desk; segments = category split, with "actual work"
// (green) anchored at the bottom so the real-work baseline is scannable across the month.
(function () {
  const { useState, useRef } = React;

  const INTRO = {
    savage:  "Every bar is a full day at the desk. Watch the real-work base.",
    deadpan: "One bar per day. Height is time logged; the cool base is real work.",
    gentle:  "Each bar is a day. The base is the research, coding and writing that landed.",
  };

  // bottom-up stacking order: real work first (sits at the base), leaks above
  const ORDER = ["research", "coding", "writing", "admin", "personal"];

  function aggDay(day) {
    const sums = {};
    day.events.forEach((e) => {
      sums[e.cat] = (sums[e.cat] || 0) + (window.toMin(e.end) - window.toMin(e.start));
    });
    let leak = null, lv = -1;
    const REAL = window.WL_REAL || ["research", "coding", "writing"];
    Object.keys(sums).forEach((k) => { if (!REAL.includes(k) && sums[k] > lv) { lv = sums[k]; leak = k; } });
    if (!leak) leak = Object.keys(sums).sort((a, b) => sums[b] - sums[a])[0];
    return { sums, leak };
  }

  function BarTip({ M, cats, idx, cx }) {
    const d = M.days[idx];
    const { sums, leak } = aggDay(d);
    return (
      <div className="wl-bartip" style={{ left: `clamp(98px, ${cx}px, calc(100% - 98px))` }}>
        <span className="wl-tip-head">
          <span className="wl-tip-time">{d.dateShort}</span>
          <span className="wl-tip-dur">{window.fmtDur(d.logged)}</span>
        </span>
        <span className="wl-cal-tip-row"><b>{window.fmtDur(d.real)}</b> real work</span>
        <span className="wl-cal-tip-row wl-cal-tip-leak">
          <span className="wl-dot" style={{ background: cats[leak].color }} />
          mostly {cats[leak].label.toLowerCase()}
        </span>
      </div>
    );
  }

  window.MonthBars = function MonthBars({ M, tone = "savage", cats, onSelectDay }) {
    const C = cats || M.cats;
    const [hover, setHover] = useState(null);
    const plotRef = useRef(null);

    const maxLogged = Math.max(...M.days.map((d) => d.logged));
    const scaleH = Math.max(2, Math.ceil(maxLogged / 60));
    const scaleMax = scaleH * 60;
    const gridlines = [];
    for (let h = 2; h <= scaleH; h += 2) gridlines.push(h);

    // group days into Mon–Sun week rows
    const weeks = [];
    let wk = [];
    const col = (dow) => (dow + 6) % 7;
    M.days.forEach((d, idx) => { wk.push({ d, idx }); if (col(d.dow) === 6) { weeks.push(wk); wk = []; } });
    if (wk.length) weeks.push(wk);

    return (
      <div className="wl-body">
        <div className="wl-daterow">
          <div className="wl-datenav"><span className="wl-date">{M.month}</span></div>
          <span className="wl-tag">{M.days.length} days</span>
        </div>

        <p className="wl-month-intro">{INTRO[tone] || INTRO.savage}</p>

        <div className="wl-bars-legend">
          {["research", "coding", "writing", "admin", "personal"].map((k) => (
            <span key={k} className="wl-bars-leg">
              <span className="wl-dot" style={{ background: C[k].color }} />{C[k].label}
            </span>
          ))}
        </div>

        <div className="wl-bars-plot" ref={plotRef} onMouseLeave={() => setHover(null)}>
          <div className="wl-bars-grid">
            {gridlines.map((h) => (
              <span key={h} className="wl-bars-line" style={{ bottom: (h * 60 / scaleMax * 100) + "%" }}>
                <span>{h}h</span>
              </span>
            ))}
          </div>
          {weeks.map((week, wi) => (
            <div className="wl-bars-week" key={wi} style={{ flex: week.length }}>
              {week.map(({ d, idx }) => {
                const { sums } = aggDay(d);
                const colH = (d.logged / scaleMax) * 100;
                return (
                  <div
                    key={idx}
                    className="wl-bar-col"
                    onClick={() => onSelectDay(idx)}
                    onMouseEnter={(e) => {
                      const pr = plotRef.current.getBoundingClientRect();
                      const cr = e.currentTarget.getBoundingClientRect();
                      setHover({ idx, cx: cr.left + cr.width / 2 - pr.left });
                    }}
                  >
                    <div className="wl-bar" style={{ height: colH + "%" }}>
                      {ORDER.map((k) => (sums[k] ? (
                        <span key={k} className="wl-bar-seg"
                          style={{ height: (sums[k] / d.logged * 100) + "%", background: C[k].color }} />
                      ) : null))}
                    </div>
                  </div>
                );
              })}
            </div>
          ))}
          {hover && <BarTip M={M} cats={C} idx={hover.idx} cx={hover.cx} />}
        </div>

        <div className="wl-bars-days">
          {weeks.map((week, wi) => (
            <div className="wl-bars-dweek" key={wi} style={{ flex: week.length }}>
              {week.map(({ d, idx }) => <span key={idx} className="wl-bars-dnum">{d.dayNum}</span>)}
            </div>
          ))}
        </div>

        <div className="wl-cal-scale">
          <span>bar height = hours at the desk · cool base = real work</span>
          <span className="wl-cal-hint">click a day to open it</span>
        </div>
      </div>
    );
  };
})();

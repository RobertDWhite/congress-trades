// Transparent Conflict Score v2: a 0-100 gauge plus the per-component breakdown so the
// number is fully auditable. `score` is the dossier's conflict_score object.
export default function ConflictScore({ score, compact = false }) {
  if (!score) return null
  const lvl = score.level || 'none'
  const components = score.components || []

  return (
    <div className={`conflict-score cs-${lvl}`}>
      <div className="cs-head">
        <div className="cs-gauge">
          <div className="cs-num num">{score.score}</div>
          <div className="cs-of">/ 100</div>
        </div>
        <div className="cs-head-meta">
          <div className="cs-title">
            Conflict context score <span className={`cs-pill cs-pill-${lvl}`}>{lvl}</span>
          </div>
          <div className="muted cs-summary">
            {score.summary?.length ? score.summary.join(' · ') : 'No elevated context found.'}
          </div>
        </div>
      </div>

      {!compact && (
        <>
          <div className="cs-components">
            {components.map((c) => (
              <div key={c.key} className={`cs-row ${c.points > 0 ? 'on' : 'off'}`}>
                <div className="cs-row-top">
                  <span className="cs-label">{c.label}</span>
                  <span className="cs-pts num">{c.points}<span className="muted">/{c.max}</span></span>
                </div>
                <div className="cs-bar"><span style={{ width: `${Math.round((c.points / c.max) * 100)}%` }} /></div>
                <div className="cs-detail muted">{c.detail}</div>
              </div>
            ))}
          </div>
          {score.methodology && <p className="note cs-method">{score.methodology}</p>}
        </>
      )}
    </div>
  )
}

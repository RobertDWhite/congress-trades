import { useEffect, useState } from 'react'
import { api } from '../api.js'

export default function Methodology() {
  const [meta, setMeta] = useState(null)
  useEffect(() => { api.meta().then(setMeta).catch(() => setMeta(null)) }, [])

  return (
    <>
      <h1>Methodology &amp; Data</h1>
      <div className="disclaimer-banner">
        Everything here is built from <strong>public</strong> disclosures filed under the STOCK Act, plus free public datasets.
        Disclosed trades are legal. Nothing on this site is financial advice or an allegation of wrongdoing.
      </div>

      <h2>How the Conflict Score works</h2>
      <div className="panel">
        <p>The 0–100 conflict-context score is <strong>additive and fully transparent</strong> — seven weighted, capped components:</p>
        <ul>
          <li><strong>Committee / sector overlap (22)</strong> — member oversees the traded company’s sector.</li>
          <li><strong>Member vote near trade (20)</strong> — a related floor vote close in time.</li>
          <li><strong>Trade size vs member history (16)</strong> — unusually large for this member.</li>
          <li><strong>Clustered congressional activity (14)</strong> — multiple members in the same name.</li>
          <li><strong>Disclosure lateness (12)</strong> — past the 45-day STOCK Act window.</li>
          <li><strong>Company event proximity (10)</strong> — SEC 8-K / Form 4 near the trade.</li>
          <li><strong>SEC fundamentals context (6)</strong> — traded near a reporting period.</li>
        </ul>
        <p className="muted">Every dossier shows the per-component points, so the number is auditable — it’s context for research, not a verdict.</p>
      </div>

      <h2>Disclosure lag</h2>
      <div className="panel">
        <p>The STOCK Act requires members to disclose trades within <strong>45 days</strong>. So this data is delayed by up to ~45 days
        and is <strong>never real-time</strong>. All "returns" are a hypothetical follower’s, measured from the public disclosure date
        (not the trade date) and benchmarked against SPY.</p>
      </div>

      <h2>Data sources</h2>
      <div className="panel" style={{ padding: 0, overflowX: 'auto' }}>
        <table>
          <thead><tr><th>Source</th><th>What it provides</th></tr></thead>
          <tbody>
            {(meta?.data_sources || []).map((s) => (
              <tr key={s.name}><td><strong>{s.name}</strong></td><td className="muted">{s.what}</td></tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>Developer API</h2>
      <div className="panel">
        <p>The data is available as a free, read-only JSON API. Interactive docs: <a href="/docs" target="_blank" rel="noopener noreferrer">/docs</a> ·
          OpenAPI spec: <a href="/openapi.json" target="_blank" rel="noopener noreferrer">/openapi.json</a> ·
          CSV: <a href="/api/export/trades.csv" target="_blank" rel="noopener noreferrer">export</a> ·
          RSS: <a href="/api/feed.rss" target="_blank" rel="noopener noreferrer">feed</a></p>
        <div className="news-list">
          {(meta?.endpoints || []).map((e) => <code key={e} style={{ display: 'block', padding: '4px 0' }}>{e}</code>)}
        </div>
      </div>
      <p className="note">{meta?.disclaimer}</p>
    </>
  )
}

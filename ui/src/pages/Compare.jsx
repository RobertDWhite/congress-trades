import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, compactMoney, pct } from '../api.js'
import PartyBadge from '../components/PartyBadge.jsx'

export default function Compare() {
  const [q, setQ] = useState('')
  const [results, setResults] = useState([])
  const [ids, setIds] = useState([])
  const [data, setData] = useState([])

  useEffect(() => {
    if (q.trim().length < 2) { setResults([]); return }
    api.members({ q, limit: 8 }).then((d) => setResults(d.items || [])).catch(() => setResults([]))
  }, [q])

  useEffect(() => {
    if (!ids.length) { setData([]); return }
    api.membersCompare(ids).then((d) => setData(d.items || [])).catch(() => setData([]))
  }, [ids])

  const add = (m) => { if (!ids.includes(m.id) && ids.length < 4) setIds([...ids, m.id]); setQ(''); setResults([]) }
  const remove = (id) => setIds(ids.filter((x) => x !== id))

  const ROWS = [
    ['Party', (m) => m.party || '—'],
    ['Chamber / State', (m) => `${m.chamber || '—'} · ${m.state || '—'}`],
    ['Disclosed trades', (m) => (m.trade_count || 0).toLocaleString()],
    ['Buys / Sells', (m) => `${m.buys || 0} / ${m.sells || 0}`],
    ['Est. volume', (m) => compactMoney(m.est_volume)],
    ['Avg disclosure lag', (m) => (m.avg_lag_days != null ? `${Math.round(m.avg_lag_days)}d` : '—')],
    ['% late (>45d)', (m) => (m.pct_late != null ? `${Math.round(m.pct_late * 100)}%` : '—')],
    ['Excess vs SPY', (m) => pct(m.wt_excess_pct)],
    ['Top sectors', (m) => (m.top_sectors || []).slice(0, 3).map((s) => s.sector).join(', ') || '—'],
  ]

  return (
    <>
      <h1>Compare Members</h1>
      <p className="note">Add up to four members for a side-by-side of volume, timing, performance, and sector mix.</p>
      <div className="filters" style={{ position: 'relative' }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search members to add…" />
        {results.length > 0 && (
          <div className="search-results" style={{ top: 38, left: 0 }}>
            {results.map((m) => (
              <a key={m.id} onClick={() => add(m)} style={{ cursor: 'pointer' }}>{m.full_name} <span className="muted">{m.party} · {m.state}</span></a>
            ))}
          </div>
        )}
      </div>

      {data.length === 0 ? <p className="muted">No members selected yet.</p> : (
        <div className="panel" style={{ padding: 0, overflowX: 'auto' }}>
          <table>
            <thead>
              <tr>
                <th></th>
                {data.map((m) => (
                  <th key={m.id}>
                    <Link to={`/members/${m.id}`}>{m.full_name}</Link> <PartyBadge party={m.party} />
                    <button className="btn-sm" style={{ marginLeft: 6 }} onClick={() => remove(m.id)}>✕</button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ROWS.map(([label, fn]) => (
                <tr key={label}>
                  <td className="muted nowrap">{label}</td>
                  {data.map((m) => <td key={m.id} className="num">{fn(m)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

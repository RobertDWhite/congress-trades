import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, amountRange, compactMoney, pct, typeClass } from '../api.js'
import PartyBadge from '../components/PartyBadge.jsx'
import { SkeletonCards } from '../components/Skeleton.jsx'

function MacroStrip() {
  const [m, setM] = useState(null)
  useEffect(() => { api.macro().then((d) => setM(d.items || [])).catch(() => setM([])) }, [])
  if (!m || !m.length) return null
  return (
    <div className="cards" style={{ marginBottom: 16 }}>
      {m.map((s) => (
        <div key={s.series_id} className="card">
          <div className="label">{s.title}</div>
          <div className="big num">{s.value != null ? s.value.toLocaleString() : '—'}{s.units && s.units.includes('Percent') ? '%' : ''}</div>
          {s.change != null && <div className={`note ${s.change >= 0 ? 'pos' : 'neg'}`}>{s.change >= 0 ? '+' : ''}{s.change.toFixed(2)} vs prior</div>}
        </div>
      ))}
    </div>
  )
}

function NewPositions() {
  const [days, setDays] = useState(30)
  const [d, setD] = useState(undefined)
  useEffect(() => { setD(undefined); api.newPositions({ days, limit: 100 }).then(setD).catch(() => setD(null)) }, [days])
  return (
    <>
      <div className="filters">
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
          <option value="14">14 days</option><option value="30">30 days</option><option value="90">90 days</option>
        </select>
      </div>
      {d === undefined ? <SkeletonCards n={2} /> : d === null ? <p className="muted">Couldn’t load.</p> : (
        <div className="panel" style={{ padding: 0, overflowX: 'auto' }}>
          <table>
            <thead><tr><th>Member</th><th>Ticker</th><th className="right">Amount</th><th>Traded</th><th>Disclosed</th></tr></thead>
            <tbody>
              {(d.items || []).map((t) => (
                <tr key={t.id}>
                  <td className="nowrap">{t.member_id ? <Link to={`/members/${t.member_id}`}>{t.member}</Link> : t.member} <PartyBadge party={t.party} /></td>
                  <td>{t.ticker ? <Link to={`/tickers/${t.ticker}`}>{t.ticker}</Link> : '—'}</td>
                  <td className="right num">{amountRange(t)}</td>
                  <td className="muted nowrap">{t.transaction_date || '—'}</td>
                  <td className="muted nowrap"><Link to={`/trade/${t.id}`}>{t.disclosure_date || '—'}</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="note">A member’s first-ever disclosed buy of a ticker — the strongest "new conviction" signal.</p>
    </>
  )
}

function SectorRotation() {
  const [d, setD] = useState(undefined)
  useEffect(() => { api.sectorRotation(365).then(setD).catch(() => setD(null)) }, [])
  const maxAbs = useMemo(() => {
    let mx = 1
    for (const row of d?.matrix || []) for (const c of row.cells) mx = Math.max(mx, Math.abs(c.net))
    return mx
  }, [d])
  if (d === undefined) return <SkeletonCards n={2} />
  if (d === null) return <p className="muted">Couldn’t load sector rotation.</p>
  const cellColor = (net) => {
    if (!net) return 'transparent'
    const a = Math.min(0.85, 0.12 + Math.abs(net) / maxAbs)
    return net > 0 ? `rgba(63,185,80,${a})` : `rgba(248,81,73,${a})`
  }
  return (
    <>
      <p className="note">Net buy (green) vs sell (red) pressure by sector by month — watch Congress rotate between sectors.</p>
      <div className="panel" style={{ padding: 0, overflowX: 'auto' }}>
        <table className="heatmap">
          <thead><tr><th>Sector</th>{d.months.map((m) => <th key={m} className="right">{m.slice(2)}</th>)}</tr></thead>
          <tbody>
            {d.matrix.map((row) => (
              <tr key={row.sector}>
                <td className="nowrap">{row.sector}</td>
                {row.cells.map((c) => (
                  <td key={c.month} className="right num" style={{ background: cellColor(c.net) }}
                      title={`${row.sector} ${c.month}: ${c.buys} buys / ${c.sells} sells`}>
                    {c.net ? compactMoney(c.net) : ''}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

function Owners() {
  const [d, setD] = useState(undefined)
  useEffect(() => { api.owners({ days: 365 }).then(setD).catch(() => setD(null)) }, [])
  if (d === undefined) return <SkeletonCards n={2} />
  if (d === null) return <p className="muted">Couldn’t load.</p>
  return (
    <>
      <div className="cards">
        {d.breakdown.map((b) => (
          <div key={b.owner} className="card"><div className="label">{b.owner}</div><div className="big num">{b.count}</div><div className="note">{compactMoney(b.volume)}</div></div>
        ))}
      </div>
      <h3 style={{ marginTop: 16 }}>Spouse / dependent / joint trades</h3>
      <div className="panel" style={{ padding: 0, overflowX: 'auto' }}>
        <table>
          <thead><tr><th>Member</th><th>Owner</th><th>Ticker</th><th>Type</th><th className="right">Amount</th><th>Disclosed</th></tr></thead>
          <tbody>
            {(d.non_self_trades || []).map((t) => (
              <tr key={t.id}>
                <td className="nowrap">{t.member_id ? <Link to={`/members/${t.member_id}`}>{t.member}</Link> : t.member}</td>
                <td className="muted">{t.owner}</td>
                <td>{t.ticker ? <Link to={`/tickers/${t.ticker}`}>{t.ticker}</Link> : '—'}</td>
                <td><span className={`tag ${typeClass(t.transaction_type)}`}>{t.transaction_type}</span></td>
                <td className="right num">{amountRange(t)}</td>
                <td className="muted nowrap"><Link to={`/trade/${t.id}`}>{t.disclosure_date || '—'}</Link></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

const TABS = [
  { k: 'new', label: 'New positions', el: <NewPositions /> },
  { k: 'rotation', label: 'Sector rotation', el: <SectorRotation /> },
  { k: 'owners', label: 'Owners / spouses', el: <Owners /> },
]

export default function Discover() {
  const [tab, setTab] = useState('new')
  return (
    <>
      <h1>Discover</h1>
      <MacroStrip />
      <div className="filters">
        {TABS.map((t) => <button key={t.k} className={`btn ${tab === t.k ? 'active' : ''}`} onClick={() => setTab(t.k)}>{t.label}</button>)}
      </div>
      {TABS.find((t) => t.k === tab)?.el}
    </>
  )
}

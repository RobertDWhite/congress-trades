import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, compactMoney, signalLabel } from '../api.js'
import Conviction from '../components/Conviction.jsx'
import TradeProvenance from '../components/TradeProvenance.jsx'

function ResearchRow({ item, onOpen }) {
  const t = item.trade || {}
  return (
    <tr>
      <td>
        <button className="linklike" onClick={() => onOpen(t.id)}>{t.ticker || t.asset_name || 'Trade'}</button>
        <div className="muted">{item.reasons?.join(' · ')}</div>
      </td>
      <td>{t.member_id ? <Link to={`/members/${t.member_id}`}>{t.member}</Link> : t.member}</td>
      <td className="right num">{item.unusual_score}</td>
      <td><Conviction score={t.conviction} /></td>
      <td className="right num">{compactMoney(((t.amount_min || 0) + (t.amount_max || t.amount_min || 0)) / 2)}</td>
      <td>{(t.signals || []).map((s) => <span key={s.type} className={`tag sig sig-${s.type}`}>{signalLabel(s.type)}</span>)}</td>
      <td className="muted nowrap">{t.disclosure_date || '—'}</td>
    </tr>
  )
}

export default function Research() {
  const [days, setDays] = useState(90)
  const [ticker, setTicker] = useState('')
  const [data, setData] = useState(undefined)
  const [alerts, setAlerts] = useState(undefined)
  const [detailId, setDetailId] = useState(null)

  useEffect(() => {
    setData(undefined)
    setAlerts(undefined)
    const params = { days, ticker: ticker.trim().toUpperCase(), limit: 50 }
    api.unusualActivity(params).then(setData).catch(() => setData(null))
    api.alertCandidates({ ...params, min_conviction: 50 }).then(setAlerts).catch(() => setAlerts(null))
  }, [days, ticker])

  return (
    <>
      <h1>Research Queue</h1>
      <p className="note">Triage trades worth deeper review: large ranges, high conviction, cluster activity, late disclosure, policy context, SEC events, and first-observed member/ticker activity. Not advice or an allegation.</p>
      <div className="filters">
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
          <option value="30">30 days</option>
          <option value="90">90 days</option>
          <option value="180">180 days</option>
          <option value="365">1 year</option>
        </select>
        <input value={ticker} onChange={(e) => setTicker(e.target.value)} placeholder="Ticker filter" />
      </div>

      <div className="cards">
        <div className="card"><div className="label">Unusual trades</div><div className="big num">{data?.items?.length ?? '—'}</div></div>
        <div className="card"><div className="label">Alert candidates</div><div className="big num">{alerts?.items?.length ?? '—'}</div></div>
        <div className="card"><div className="label">Window</div><div className="big num">{days}d</div></div>
      </div>

      <h2>Unusual Activity</h2>
      {data === undefined ? <div className="loading">Loading…</div>
        : data === null ? <p className="muted">Couldn’t load unusual activity.</p>
        : (
          <div className="panel" style={{ padding: 0, overflowX: 'auto' }}>
            <table>
              <thead><tr><th>Trade</th><th>Member</th><th className="right">Unusual</th><th>Conviction</th><th className="right">Amount</th><th>Signals</th><th>Disclosed</th></tr></thead>
              <tbody>{(data.items || []).map((item) => <ResearchRow key={item.trade?.id} item={item} onOpen={setDetailId} />)}</tbody>
            </table>
          </div>
        )}

      {alerts?.items?.length > 0 && (
        <>
          <h2>Alert Candidates</h2>
          <div className="panel">
            <div className="news-list">
              {alerts.items.slice(0, 20).map((a) => (
                <button key={a.trade?.id} className="linklike research-alert" onClick={() => setDetailId(a.trade?.id)}>
                  {a.trade?.ticker || a.trade?.asset_name} · {a.trade?.member}<span className="src"> · {a.reasons.join(' · ')}</span>
                </button>
              ))}
            </div>
          </div>
        </>
      )}

      {detailId && <TradeProvenance tradeId={detailId} onClose={() => setDetailId(null)} />}
    </>
  )
}

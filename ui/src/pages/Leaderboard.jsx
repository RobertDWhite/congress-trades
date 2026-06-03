import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, compactMoney, gradeClass, pct } from '../api.js'
import PartyBadge from '../components/PartyBadge.jsx'
import { SkeletonTable } from '../components/Skeleton.jsx'

const TABS = [
  { k: 'performance', label: 'Performance vs SPY' },
  { k: 'conflict', label: 'Oversight conflict' },
  { k: 'compliance', label: 'STOCK Act grade' },
  { k: 'prescience', label: 'Prescience' },
  { k: 'volume', label: 'Disclosed volume' },
  { k: 'activity', label: 'Most active' },
  { k: 'late', label: 'Latest disclosers' },
]

function rankCls(i) { return `rank rank-${i + 1 <= 3 ? i + 1 : ''}` }

export default function Leaderboard() {
  const [tab, setTab] = useState('performance')
  const [d, setD] = useState(undefined)

  useEffect(() => {
    setD(undefined)
    const p = tab === 'prescience' ? api.prescience({ limit: 60 }) : api.leaderboard({ metric: tab, limit: 60 })
    p.then(setD).catch(() => setD(null))
  }, [tab])

  return (
    <>
      <h1>Leaderboard</h1>
      <div className="filters">
        {TABS.map((t) => (
          <button key={t.k} className={`btn ${tab === t.k ? 'active' : ''}`} onClick={() => setTab(t.k)}>{t.label}</button>
        ))}
      </div>
      {d?.note && <div className="disclaimer-banner">{d.note}</div>}

      {d === undefined ? <SkeletonTable rows={10} />
        : d === null ? <p className="muted">Couldn’t load leaderboard.</p>
        : (
        <div className="panel" style={{ padding: 0, overflowX: 'auto' }}>
          <table>
            <thead>
              <tr>
                <th>#</th><th>Member</th><th>Chamber</th>
                {tab === 'performance' && <><th className="right">Excess vs SPY</th><th className="right">Hit rate</th><th className="right">Trades</th></>}
                {tab === 'conflict' && <><th className="right">Conflict trades</th><th className="right">Conflict rate</th><th className="right">Trades</th></>}
                {tab === 'compliance' && <><th className="right">Grade</th><th className="right">Late rate</th><th className="right">Avg lag</th></>}
                {tab === 'prescience' && <><th className="right">Well-timed</th><th className="right">8-K buys</th><th className="right">Avg excess</th></>}
                {['volume', 'activity', 'late'].includes(tab) && <><th className="right">Trades</th><th className="right">Volume</th><th className="right">Avg lag</th></>}
              </tr>
            </thead>
            <tbody>
              {(d.items || []).map((m, i) => (
                <tr key={m.id}>
                  <td><span className={rankCls(i)}>{i + 1}</span></td>
                  <td className="nowrap"><Link to={`/members/${m.id}`}>{m.full_name}</Link> <PartyBadge party={m.party} /></td>
                  <td className={`chamber-${m.chamber}`}>{m.chamber || '—'}</td>
                  {tab === 'performance' && <>
                    <td className={`right num ${m.wt_excess_pct >= 0 ? 'pos' : 'neg'}`}>{pct(m.wt_excess_pct)}</td>
                    <td className="right num">{Math.round((m.hit_rate || 0) * 100)}%</td>
                    <td className="right num">{m.n}</td>
                  </>}
                  {tab === 'conflict' && <>
                    <td className="right num">{m.conflict_trades}</td>
                    <td className="right num neg">{Math.round((m.conflict_rate || 0) * 100)}%</td>
                    <td className="right num">{(m.trade_count || 0).toLocaleString()}</td>
                  </>}
                  {tab === 'compliance' && <>
                    <td className="right"><span className={`grade ${gradeClass(m.grade)}`}>{m.grade}</span></td>
                    <td className="right num">{Math.round((m.late_rate || 0) * 100)}%</td>
                    <td className="right num">{m.avg_lag_days != null ? `${Math.round(m.avg_lag_days)}d` : '—'}</td>
                  </>}
                  {tab === 'prescience' && <>
                    <td className="right num">{m.well_timed}</td>
                    <td className="right num">{m.corp_event_buys}</td>
                    <td className={`right num ${(m.avg_excess_pct || 0) >= 0 ? 'pos' : 'neg'}`}>{pct(m.avg_excess_pct)}</td>
                  </>}
                  {['volume', 'activity', 'late'].includes(tab) && <>
                    <td className="right num">{(m.trade_count || 0).toLocaleString()}</td>
                    <td className="right num">{compactMoney(m.est_volume)}</td>
                    <td className="right num">{m.avg_lag_days != null ? `${Math.round(m.avg_lag_days)}d` : '—'}</td>
                  </>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

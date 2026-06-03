import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, amountRange, money } from '../api.js'
import PartyBadge from '../components/PartyBadge.jsx'
import { SkeletonCards } from '../components/Skeleton.jsx'

export default function Options() {
  const [days, setDays] = useState(180)
  const [d, setD] = useState(undefined)

  useEffect(() => { setD(undefined); api.discoverOptions({ days, limit: 150 }).then(setD).catch(() => setD(null)) }, [days])

  return (
    <>
      <h1>Options Activity</h1>
      <p className="note">Disclosed options &amp; derivative positions — leveraged directional bets, the highest-conviction plays. Moneyness compares the strike to the latest price. Informational only, lagged up to 45 days.</p>
      <div className="filters">
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
          <option value="90">90 days</option><option value="180">180 days</option><option value="365">1 year</option><option value="730">2 years</option>
        </select>
      </div>

      {d === undefined ? <SkeletonCards n={3} />
        : d === null ? <p className="muted">Couldn’t load options activity.</p>
        : (
        <>
          <div className="cards">
            <div className="card"><div className="label">Calls</div><div className="big num pos">{d.calls}</div></div>
            <div className="card"><div className="label">Puts</div><div className="big num neg">{d.puts}</div></div>
            <div className="card"><div className="label">Window</div><div className="big num">{days}d</div></div>
          </div>

          {d.top_members?.length > 0 && (
            <div className="panel" style={{ marginTop: 16 }}>
              <h3>Most active in options</h3>
              <div>{d.top_members.map((m) => (
                <Link key={m.member_id} to={`/members/${m.member_id}`} className="chip">{m.member} · {m.count}</Link>
              ))}</div>
            </div>
          )}

          <div className="panel" style={{ padding: 0, overflowX: 'auto', marginTop: 16 }}>
            <table>
              <thead><tr><th>Member</th><th>Ticker</th><th>Type</th><th className="right">Strike</th><th className="right">Underlying</th><th>Moneyness</th><th className="right">Amount</th><th>Expiry</th><th>Disclosed</th></tr></thead>
              <tbody>
                {(d.items || []).map((t) => (
                  <tr key={t.id}>
                    <td className="nowrap">{t.member_id ? <Link to={`/members/${t.member_id}`}>{t.member}</Link> : t.member} <PartyBadge party={t.party} /></td>
                    <td>{t.ticker ? <Link to={`/tickers/${t.ticker}`}>{t.ticker}</Link> : '—'}</td>
                    <td><span className={`tag ${t.option_type === 'put' ? 'sell' : 'buy'}`}>{t.option_type || '—'}</span></td>
                    <td className="right num">{t.strike != null ? money(t.strike) : '—'}</td>
                    <td className="right num">{t.underlying_price != null ? money(t.underlying_price) : '—'}</td>
                    <td>{t.moneyness ? <span className={`tag ${t.moneyness === 'ITM' ? 'buy' : 'other'}`}>{t.moneyness}</span> : '—'}</td>
                    <td className="right num">{amountRange(t)}</td>
                    <td className="muted nowrap">{t.expiration || '—'}</td>
                    <td className="muted nowrap"><Link to={`/trade/${t.id}`}>{t.disclosure_date || '—'}</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="note">{d.disclaimer}</p>
        </>
      )}
    </>
  )
}

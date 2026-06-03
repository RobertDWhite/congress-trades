import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, compactMoney, pct } from '../api.js'
import Conviction from '../components/Conviction.jsx'
import { SkeletonCards } from '../components/Skeleton.jsx'

const TT = { background: '#161b22', border: '1px solid #30363d', borderRadius: 6, fontSize: 12 }

function Curve({ curve }) {
  return (
    <ResponsiveContainer width="100%" height={300}>
      <LineChart data={(curve || []).map(([d, p, s]) => ({ d, port: p, spy: s }))} margin={{ top: 6, right: 8, left: -10, bottom: 0 }}>
        <CartesianGrid stroke="#21262d" vertical={false} />
        <XAxis dataKey="d" stroke="#8b949e" fontSize={11} tickFormatter={(d) => (d || '').slice(0, 7)} minTickGap={40} />
        <YAxis stroke="#8b949e" fontSize={11} domain={['auto', 'auto']} />
        <Tooltip contentStyle={TT} />
        <Line type="monotone" dataKey="port" stroke="#3fb950" dot={false} strokeWidth={2} isAnimationActive={false} name="strategy" />
        <Line type="monotone" dataKey="spy" stroke="#8b949e" dot={false} strokeWidth={1.5} isAnimationActive={false} name="SPY" />
      </LineChart>
    </ResponsiveContainer>
  )
}

function Builder() {
  const [p, setP] = useState({ cohort: 'all', ignore_late: false, clusters_only: false, min_conviction: 0, weighting: 'equal' })
  const [res, setRes] = useState(undefined)
  const run = () => { setRes(null); api.customBacktest(p).then(setRes).catch(() => setRes(false)) }
  return (
    <div className="panel" style={{ marginTop: 16 }}>
      <h3>Build your own backtest</h3>
      <div className="filters">
        <select value={p.cohort} onChange={(e) => setP({ ...p, cohort: e.target.value })}>
          <option value="all">All Congress</option><option value="democrat">Democrats</option><option value="republican">Republicans</option>
        </select>
        <select value={p.weighting} onChange={(e) => setP({ ...p, weighting: e.target.value })}>
          <option value="equal">Equal weight</option><option value="notional">Notional weight</option>
        </select>
        <select value={p.min_conviction} onChange={(e) => setP({ ...p, min_conviction: Number(e.target.value) })}>
          <option value="0">Any conviction</option><option value="30">Conviction ≥ 30</option><option value="50">Conviction ≥ 50</option>
        </select>
        <label className="muted"><input type="checkbox" checked={p.ignore_late} onChange={(e) => setP({ ...p, ignore_late: e.target.checked })} /> ignore late</label>
        <label className="muted"><input type="checkbox" checked={p.clusters_only} onChange={(e) => setP({ ...p, clusters_only: e.target.checked })} /> clusters only</label>
        <button className="btn active" onClick={run}>Run</button>
      </div>
      {res === null ? <p className="muted">Running…</p>
        : res === false ? <p className="muted">Couldn’t run backtest.</p>
        : res ? (
          <>
            <div className="cards">
              <div className="card"><div className="label">Total return</div><div className={`big num ${res.total_return >= 0 ? 'pos' : 'neg'}`}>{pct(res.total_return)}</div></div>
              <div className="card"><div className="label">Excess vs SPY</div><div className={`big num ${res.excess_vs_spy >= 0 ? 'pos' : 'neg'}`}>{pct(res.excess_vs_spy)}</div></div>
              <div className="card"><div className="label">Max drawdown</div><div className="big num neg">{pct(res.max_drawdown)}</div></div>
              <div className="card"><div className="label">Positions</div><div className="big num">{res.n_positions || 0}</div></div>
            </div>
            <Curve curve={res.equity_curve} />
          </>
        ) : null}
    </div>
  )
}

function EtfOverlap() {
  const [d, setD] = useState(undefined)
  useEffect(() => { api.etfOverlap({ days: 90, limit: 25 }).then(setD).catch(() => setD(null)) }, [])
  if (!d || d === null) return null
  return (
    <>
      <h2 style={{ marginTop: 24 }}>Congress ETFs <span className="muted" style={{ fontWeight: 400, fontSize: 13 }}>NANC / KRUZ holdings vs our accumulation</span></h2>
      <div className="grid-2">
        {Object.entries(d.etfs || {}).map(([etf, holds]) => (
          <div key={etf} className="panel" style={{ padding: 0 }}>
            <h3 style={{ padding: '12px 16px 0' }}>{etf}</h3>
            <table>
              <thead><tr><th>Ticker</th><th className="right">Weight</th><th>In our basket</th></tr></thead>
              <tbody>
                {holds.slice(0, 15).map((h) => (
                  <tr key={h.ticker}>
                    <td><Link to={`/tickers/${h.ticker}`}>{h.ticker}</Link></td>
                    <td className="right num">{h.weight != null ? `${(h.weight * 100).toFixed(1)}%` : '—'}</td>
                    <td>{h.in_recent_accumulation ? <span className="tag buy">yes</span> : <span className="muted">—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
      <p className="note">{d.note}</p>
    </>
  )
}

export default function Strategies() {
  const [list, setList] = useState(undefined)
  const [key, setKey] = useState(null)
  const [detail, setDetail] = useState(null)

  useEffect(() => {
    api.strategies().then((d) => { setList(d); if (d.items?.length) setKey(d.items[0].strategy_key) }).catch(() => setList(null))
  }, [])
  useEffect(() => { if (key) { setDetail(null); api.strategy(key).then(setDetail).catch(() => setDetail(false)) } }, [key])

  return (
    <>
      <h1>Strategies <span className="muted" style={{ fontWeight: 400, fontSize: 13 }}>follow-Congress backtests</span></h1>
      <div className="disclaimer-banner">
        Hypothetical backtest. Each position enters at the first close <strong>on/after the public disclosure date</strong>
        {' '}(lagged up to 45 days), price-return only, $1 per disclosed buy held to today, vs SPY. In-sample, single regime.
        Not advice; past performance does not predict future results.
      </div>

      {list === undefined ? <SkeletonCards n={5} />
        : list === null ? <p className="muted">Couldn’t load strategies.</p>
        : (
        <>
          <div className="filters">
            {list.items.map((s) => (
              <button key={s.strategy_key} className={`btn ${key === s.strategy_key ? 'active' : ''}`} onClick={() => setKey(s.strategy_key)}>
                {s.label} <span className={s.excess_vs_spy >= 0 ? 'pos' : 'neg'}>{pct(s.excess_vs_spy)}</span>
              </button>
            ))}
          </div>

          {!detail ? <SkeletonCards n={4} /> : (
            <>
              <div className="cards">
                <div className="card"><div className="label">Total return</div><div className={`big num ${detail.total_return >= 0 ? 'pos' : 'neg'}`}>{pct(detail.total_return)}</div></div>
                <div className="card"><div className="label">Excess vs SPY</div><div className={`big num ${detail.excess_vs_spy >= 0 ? 'pos' : 'neg'}`}>{pct(detail.excess_vs_spy)}</div></div>
                <div className="card"><div className="label">Max drawdown</div><div className="big num neg">{pct(detail.max_drawdown)}</div></div>
                <div className="card"><div className="label">Positions</div><div className="big num">{detail.n_positions}</div></div>
              </div>

              <div className="panel" style={{ marginTop: 16 }}>
                <h3>Equity curve vs SPY (normalized to 1.0)</h3>
                <Curve curve={detail.equity_curve} />
              </div>

              <h2>Smart-money basket <span className="muted" style={{ fontWeight: 400, fontSize: 13 }}>(net-accumulated, last 90d)</span></h2>
              <div className="panel" style={{ padding: 0, overflowX: 'auto' }}>
                <table>
                  <thead><tr><th>Ticker</th><th>Sector</th><th className="right">Net</th><th className="right">Buyers</th><th>Conviction</th></tr></thead>
                  <tbody>
                    {(detail.holdings || []).map((h) => (
                      <tr key={h.ticker}>
                        <td><Link to={`/tickers/${h.ticker}`}>{h.ticker}</Link>{h.company ? <div className="muted" style={{ fontSize: 11 }}>{h.company}</div> : null}</td>
                        <td className="muted">{h.sector || '—'}</td>
                        <td className="right num">{compactMoney(h.net_notional)}</td>
                        <td className="right num">{h.buyers}</td>
                        <td><Conviction score={h.conviction} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="note">{detail.disclaimer}</p>
            </>
          )}

          <Builder />
          <EtfOverlap />
        </>
      )}
    </>
  )
}

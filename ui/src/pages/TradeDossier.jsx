import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { CartesianGrid, Line, LineChart, ReferenceDot, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, amountRange, compactMoney, eventLabel, money, ogTradeUrl, pct, typeClass } from '../api.js'
import ConflictScore from '../components/ConflictScore.jsx'
import SourceBadge from '../components/SourceBadge.jsx'
import PartyBadge from '../components/PartyBadge.jsx'
import { SkeletonCards } from '../components/Skeleton.jsx'

const VERB = { purchase: 'bought', sale: 'sold', exchange: 'exchanged' }

function Move({ label, value, note }) {
  if (value == null) return null
  return (
    <div className="card">
      <div className="label">{label}</div>
      <div className={`big num ${value >= 0 ? 'pos' : 'neg'}`}>{pct(value)}</div>
      {note && <div className="note">{note}</div>}
    </div>
  )
}

export default function TradeDossier() {
  const { id } = useParams()
  const [d, setD] = useState(undefined)
  const [news, setNews] = useState([])

  useEffect(() => {
    setD(undefined)
    setNews([])
    api.tradeDossier(id).then(setD).catch(() => setD(null))
  }, [id])

  useEffect(() => {
    const tk = d && d.trade && d.trade.ticker
    if (tk) api.newsContext(tk).then((r) => setNews(r.items || [])).catch(() => setNews([]))
  }, [d])

  if (d === undefined) return <SkeletonCards n={3} />
  if (d === null || !d.trade) return <p className="muted">Couldn’t load this trade dossier.</p>

  const t = d.trade
  const m = d.member
  const verb = VERB[t.transaction_type] || 'traded'
  const bars = d.price_bars || []
  const pm = d.price_movement
  const fund = d.fundamentals
  const ties = d.committee_ties || {}
  const history = d.member_ticker_history || []

  const txBar = t.transaction_date ? bars.find((b) => b.date >= t.transaction_date) : null
  const discBar = t.disclosure_date ? bars.find((b) => b.date >= t.disclosure_date) : null

  return (
    <>
      <p className="note"><Link to="/research">← Research queue</Link></p>
      <h1>{t.ticker ? <Link to={`/tickers/${t.ticker}`}>{t.ticker}</Link> : (t.asset_name || 'Trade')} dossier</h1>

      <div className="dossier-head">
        <div className="dossier-line">
          <span className={`tag ${typeClass(t.transaction_type)}`}>{verb}</span>{' '}
          <strong>{t.member_id ? <Link to={`/members/${t.member_id}`}>{t.member}</Link> : (t.member || 'Unknown')}</strong>{' '}
          <PartyBadge party={t.party} />
          <span className="muted"> · {amountRange(t)}{t.asset_name && t.ticker ? ` · ${t.asset_name}` : ''}</span>
        </div>
        <div className="muted dossier-dates">
          Traded {t.transaction_date || '—'} · disclosed {t.disclosure_date || '—'}
          {t.disclosure_lag_days != null ? ` · ${t.disclosure_lag_days}-day lag` : ''}
        </div>
        <div className="prov-badges">
          {(d.provenance || []).map((p) => <SourceBadge key={p.key} source={p} />)}
          {(d.etf_membership || []).map((e) => <span key={e.etf} className="prov-badge prov-context">{e.etf} holding</span>)}
          {t.source_url && <a className="prov-badge prov-link" href={t.source_url} target="_blank" rel="noopener noreferrer">Open filing ↗</a>}
          <a className="prov-badge prov-link" href={ogTradeUrl(t.id)} target="_blank" rel="noopener noreferrer">Share card ↗</a>
        </div>
      </div>

      {d.why_notable?.length > 0 && (
        <div className="why-notable">
          <div className="why-title">Why this is notable</div>
          <ul>{d.why_notable.map((w, i) => <li key={i}>{w}</li>)}</ul>
        </div>
      )}

      <div className="grid-2">
        <div className="panel"><ConflictScore score={d.conflict_score} /></div>
        <div>
          <div className="cards">
            <div className="card">
              <div className="label">Member trades</div>
              <div className="big num">{m?.total_trades ?? '—'}</div>
              <div className="note">{m?.buys ?? 0} buys · {m?.sells ?? 0} sells</div>
            </div>
            <div className="card">
              <div className="label">Avg disclosure lag</div>
              <div className="big num">{m?.avg_lag_days != null ? Math.round(m.avg_lag_days) : '—'}<span className="muted" style={{ fontSize: 13 }}> d</span></div>
              <div className="note">{m?.pct_late != null ? `${Math.round(m.pct_late * 100)}% past 45d` : ''}</div>
            </div>
            <div className="card">
              <div className="label">Est. volume</div>
              <div className="big num">{compactMoney(m?.est_volume)}</div>
            </div>
          </div>
          <div className="panel" style={{ marginTop: 12 }}>
            <h3>Committee ties</h3>
            {ties.overlap && <p className="cs-flag">⚠ Oversees the {ties.ticker_sector} sector — and this trade is in {ties.ticker_sector}.</p>}
            {ties.committees?.length
              ? <div>{ties.committees.map((c) => <span key={c} className="chip">{c}</span>)}</div>
              : <p className="muted">No committee assignments on file.</p>}
            {ties.committee_sectors?.length > 0 && (
              <p className="note">Oversight sectors: {ties.committee_sectors.join(', ')}{ties.ticker_sector ? ` · trade sector: ${ties.ticker_sector}` : ''}</p>
            )}
          </div>
        </div>
      </div>

      {bars.length > 2 && (
        <div className="panel" style={{ marginTop: 16 }}>
          <h3>Price around the trade</h3>
          <div className="cards" style={{ marginBottom: 12 }}>
            <Move label="Since transaction" value={pm?.since_transaction_pct} />
            <Move label="Since disclosure" value={pm?.since_disclosure_pct} note="when followers could act" />
            {t.excess_pct != null && (
              <div className="card">
                <div className="label">vs S&P 500</div>
                <div className={`big num ${t.excess_pct >= 0 ? 'pos' : 'neg'}`}>{pct(t.excess_pct)}</div>
                <div className="note">follower excess</div>
              </div>
            )}
          </div>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={bars} margin={{ top: 12, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="rgba(139,148,158,.16)" vertical={false} />
              <XAxis dataKey="date" minTickGap={28} tick={{ fill: 'var(--muted)', fontSize: 11 }} />
              <YAxis domain={['dataMin', 'dataMax']} tickFormatter={(v) => `$${Math.round(v)}`} tick={{ fill: 'var(--muted)', fontSize: 11 }} width={48} />
              <Tooltip contentStyle={{ background: 'var(--panel)', border: '1px solid var(--border)' }} formatter={(v) => [`$${Number(v).toFixed(2)}`, 'Close']} />
              <Line type="monotone" dataKey="close" stroke="var(--accent)" dot={false} strokeWidth={2} />
              {txBar && <ReferenceDot x={txBar.date} y={txBar.close} r={5} fill={t.transaction_type === 'sale' ? 'var(--sell)' : 'var(--buy)'} stroke="var(--bg)" strokeWidth={2} />}
              {discBar && <ReferenceDot x={discBar.date} y={discBar.close} r={4} fill="var(--exch)" stroke="var(--bg)" strokeWidth={2} />}
            </LineChart>
          </ResponsiveContainer>
          <p className="note"><span style={{ color: t.transaction_type === 'sale' ? 'var(--sell)' : 'var(--buy)' }}>●</span> transaction · <span style={{ color: 'var(--exch)' }}>●</span> disclosure. Daily closes; context only.</p>
        </div>
      )}

      {fund && (
        <div className="panel" style={{ marginTop: 16 }}>
          <h3>Company fundamentals <span className="prov-badge prov-context">SEC EDGAR</span></h3>
          <div className="cards">
            <div className="card"><div className="label">Revenue{fund.fy ? ` (FY${String(fund.fy).slice(-2)})` : ''}</div><div className="big num">{compactMoney(fund.revenue)}</div>{fund.revenue_yoy != null && <div className={`note ${fund.revenue_yoy >= 0 ? 'pos' : 'neg'}`}>{pct(fund.revenue_yoy, 0)} YoY</div>}</div>
            <div className="card"><div className="label">Net income</div><div className={`big num ${(fund.net_income ?? 0) >= 0 ? 'pos' : 'neg'}`}>{compactMoney(fund.net_income)}</div></div>
            {fund.eps_diluted != null && <div className="card"><div className="label">Diluted EPS</div><div className="big num">{money(fund.eps_diluted)}</div></div>}
            {fund.market_cap != null && <div className="card"><div className="label">Market cap</div><div className="big num">{compactMoney(fund.market_cap)}</div></div>}
            {fund.pe_ratio != null && <div className="card"><div className="label">P/E</div><div className="big num">{fund.pe_ratio}</div></div>}
            {fund.assets != null && <div className="card"><div className="label">Total assets</div><div className="big num">{compactMoney(fund.assets)}</div></div>}
            {fund.q_revenue != null && <div className="card"><div className="label">Latest quarter rev</div><div className="big num">{compactMoney(fund.q_revenue)}</div><div className="note">{fund.q_end || ''}</div></div>}
          </div>
          <p className="note">
            {fund.company || t.ticker} · latest {fund.latest_form || 'filing'}{fund.fy_end ? ` · FY end ${fund.fy_end}` : ''}
            {fund.source_url && <> · <a href={fund.source_url} target="_blank" rel="noopener noreferrer">EDGAR filings ↗</a></>}
          </p>
        </div>
      )}

      {d.federal_contracts?.length > 0 && (
        <div className="panel" style={{ marginTop: 16 }}>
          <h3>Federal contracts <span className="prov-badge prov-context">USASpending</span></h3>
          <div className="news-list">
            {d.federal_contracts.map((c) => (
              <a key={c.award_id} href={c.url} target="_blank" rel="noopener noreferrer">
                <span className="tag src">{compactMoney(c.amount)}</span> {c.agency || 'Federal agency'}<span className="src"> · {c.type}{c.action_date ? ` · ${c.action_date}` : ''}</span>
              </a>
            ))}
          </div>
          <p className="note">Federal awards to this company. Proximity to a trade is context, not causation.</p>
        </div>
      )}

      {d.lobbying?.length > 0 && (
        <div className="panel" style={{ marginTop: 16 }}>
          <h3>Lobbying <span className="prov-badge prov-context">Senate LDA</span></h3>
          <div className="news-list">
            {d.lobbying.map((l, i) => (
              <a key={i} href={l.url || '#'} target="_blank" rel="noopener noreferrer">
                {l.registrant || 'Registrant'} for {l.client}<span className="src"> · {l.amount != null ? compactMoney(l.amount) : ''} · {l.year || ''}{l.issues?.length ? ` · ${l.issues.slice(0, 3).join(', ')}` : ''}</span>
              </a>
            ))}
          </div>
        </div>
      )}

      {history.length > 0 && (
        <>
          <h2>This member’s history in {t.ticker}</h2>
          <div className="panel" style={{ padding: 0, overflowX: 'auto' }}>
            <table>
              <thead><tr><th>Traded</th><th>Type</th><th className="right">Amount</th><th className="right">Return</th><th>Disclosed</th></tr></thead>
              <tbody>
                {history.map((h) => (
                  <tr key={h.id}>
                    <td className="nowrap">{h.transaction_date || '—'}</td>
                    <td><span className={`tag ${typeClass(h.transaction_type)}`}>{h.transaction_type}</span></td>
                    <td className="right num">{amountRange(h)}</td>
                    <td className={`right num ${(h.return_pct ?? 0) >= 0 ? 'pos' : 'neg'}`}>{h.return_pct != null ? pct(h.return_pct) : '—'}</td>
                    <td className="muted nowrap">{h.disclosure_date || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {d.vote_context?.length > 0 && (
        <div className="panel" style={{ marginTop: 16 }}>
          <h3>Member votes near the trade <span className="prov-badge prov-context">Congress.gov</span></h3>
          <div className="news-list">
            {d.vote_context.map((e) => (
              <a key={e.id} href={e.url} target="_blank" rel="noopener noreferrer">
                {e.title}<span className="src"> · {e.sector || 'vote'}{e.days_from_trade != null ? ` · ${e.days_from_trade}d from trade` : ''}</span>
              </a>
            ))}
          </div>
        </div>
      )}

      {d.policy_context?.length > 0 && (
        <div className="panel" style={{ marginTop: 16 }}>
          <h3>Policy context <span className="prov-badge prov-context">Congress.gov</span></h3>
          <div className="news-list">
            {d.policy_context.slice(0, 12).map((e) => (
              <a key={e.id} href={e.url} target="_blank" rel="noopener noreferrer">
                {e.title}<span className="src"> · {e.member || e.committee || e.sector || eventLabel(e.event_type)}{e.occurred_at ? ` · ${e.occurred_at.slice(0, 10)}` : ''}</span>
              </a>
            ))}
          </div>
          <p className="note">Nearby Congress.gov activity. Context, not causality.</p>
        </div>
      )}

      {d.sec_events?.length > 0 && (
        <div className="panel" style={{ marginTop: 16 }}>
          <h3>SEC filings near the trade <span className="prov-badge prov-context">SEC EDGAR</span></h3>
          <div className="news-list">
            {d.sec_events.slice(0, 12).map((e) => (
              <a key={e.id} href={e.url} target="_blank" rel="noopener noreferrer">
                <span className="tag src">{e.form}</span> {e.title}<span className="src"> · {e.filed_at?.slice(0, 10) || ''}</span>
              </a>
            ))}
          </div>
        </div>
      )}

      {news.length > 0 && (
        <div className="panel" style={{ marginTop: 16 }}>
          <h3>News context <span className="prov-badge prov-context">GDELT</span></h3>
          <div className="news-list">
            {news.slice(0, 8).map((n, i) => (
              <a key={i} href={n.url} target="_blank" rel="noopener noreferrer">{n.title}<span className="src"> · {n.source || ''}</span></a>
            ))}
          </div>
          <p className="note">Contextual headlines about the company — not affiliated with the member.</p>
        </div>
      )}

      <p className="note dossier-disclaimer">{d.disclaimer}</p>
    </>
  )
}

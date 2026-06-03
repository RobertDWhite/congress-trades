import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'

const RULE_TYPES = [
  { k: 'member', label: 'Member trades', fields: ['member_id'] },
  { k: 'ticker', label: 'Ticker traded', fields: ['ticker'] },
  { k: 'sector', label: 'Sector traded', fields: ['sector'] },
  { k: 'large', label: 'Large trade', fields: ['min_amount'] },
  { k: 'cluster', label: 'Cluster buy/sell', fields: [] },
  { k: 'conflict', label: 'Committee conflict', fields: [] },
  { k: 'options', label: 'Options position', fields: [] },
  { k: 'event_proximity', label: 'SEC 8-K/Form 4 near trade', fields: [] },
  { k: 'late', label: 'Late disclosure', fields: ['min_lag'] },
]
const CHANNELS = ['ntfy', 'email', 'webhook', 'discord', 'slack']

function useAccount() {
  const [token, setToken] = useState(() => localStorage.getItem('ct_account') || '')
  const create = async () => { const a = await api.accountCreate(); localStorage.setItem('ct_account', a.token); setToken(a.token) }
  const restore = (t) => { localStorage.setItem('ct_account', t); setToken(t) }
  return { token, create, restore }
}

export default function Alerts() {
  const { token, create, restore } = useAccount()
  const [rules, setRules] = useState([])
  const [form, setForm] = useState({ name: '', rule_type: 'large', params: { min_amount: 250000 }, channels: [{ type: 'ntfy', target: 'congress-trades' }] })
  const [preview, setPreview] = useState(null)
  const [restoreTok, setRestoreTok] = useState('')

  const load = () => api.alerts(token || undefined).then((d) => setRules(d.items || [])).catch(() => setRules([]))
  useEffect(() => { load() }, [token])

  const typeDef = RULE_TYPES.find((t) => t.k === form.rule_type) || RULE_TYPES[0]

  const setParam = (k, v) => setForm({ ...form, params: { ...form.params, [k]: v } })
  const setChannel = (i, patch) => setForm({ ...form, channels: form.channels.map((c, j) => j === i ? { ...c, ...patch } : c) })

  const save = async () => {
    await api.alertCreate({ ...form, account_token: token || null })
    setForm({ ...form, name: '' })
    load()
  }
  const del = async (id) => { await api.alertDelete(id); load() }
  const runPreview = async () => {
    const p = { rule_type: form.rule_type, ...form.params, limit: 25 }
    setPreview(await api.alertPreview(p).catch(() => ({ items: [] })))
  }

  return (
    <>
      <h1>Alerts</h1>
      <p className="note">Get notified when trades match your rules — via ntfy push, email, webhook, Discord or Slack. Rules sync to your account token (kept in this browser).</p>

      <div className="panel" style={{ marginBottom: 16 }}>
        <h3>Account</h3>
        {token ? (
          <p className="muted">Synced to <code>{token.slice(0, 10)}…</code> — paste this token on another device to sync. <button className="btn-sm" onClick={() => { navigator.clipboard?.writeText(token) }}>Copy token</button></p>
        ) : (
          <div className="filters">
            <button className="btn" onClick={create}>Create account</button>
            <input value={restoreTok} onChange={(e) => setRestoreTok(e.target.value)} placeholder="…or paste an existing token" />
            <button className="btn" onClick={() => restore(restoreTok)} disabled={!restoreTok}>Restore</button>
          </div>
        )}
      </div>

      <div className="panel" style={{ marginBottom: 16 }}>
        <h3>New rule</h3>
        <div className="filters">
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Rule name" />
          <select value={form.rule_type} onChange={(e) => setForm({ ...form, rule_type: e.target.value, params: {} })}>
            {RULE_TYPES.map((t) => <option key={t.k} value={t.k}>{t.label}</option>)}
          </select>
          {typeDef.fields.includes('member_id') && <input placeholder="Member ID" onChange={(e) => setParam('member_id', Number(e.target.value))} />}
          {typeDef.fields.includes('ticker') && <input placeholder="Ticker" onChange={(e) => setParam('ticker', e.target.value.toUpperCase())} />}
          {typeDef.fields.includes('sector') && <input placeholder="Sector" onChange={(e) => setParam('sector', e.target.value)} />}
          {typeDef.fields.includes('min_amount') && <input placeholder="Min $ amount" defaultValue={250000} onChange={(e) => setParam('min_amount', Number(e.target.value))} />}
          {typeDef.fields.includes('min_lag') && <input placeholder="Min lag days" defaultValue={45} onChange={(e) => setParam('min_lag', Number(e.target.value))} />}
        </div>
        <div className="filters">
          {form.channels.map((c, i) => (
            <span key={i} className="filters" style={{ gap: 4 }}>
              <select value={c.type} onChange={(e) => setChannel(i, { type: e.target.value })}>
                {CHANNELS.map((ch) => <option key={ch} value={ch}>{ch}</option>)}
              </select>
              <input value={c.target} onChange={(e) => setChannel(i, { target: e.target.value })} placeholder={c.type === 'email' ? 'you@email' : c.type === 'ntfy' ? 'topic' : 'URL'} />
            </span>
          ))}
          <button className="btn-sm" onClick={() => setForm({ ...form, channels: [...form.channels, { type: 'email', target: '' }] })}>+ channel</button>
        </div>
        <div className="filters">
          <button className="btn active" onClick={save} disabled={!form.name}>Save rule</button>
          <button className="btn" onClick={runPreview}>Preview matches</button>
        </div>
      </div>

      {preview && (
        <div className="panel" style={{ marginBottom: 16 }}>
          <h3>Preview — {preview.match_count} recent match(es)</h3>
          <div className="news-list">
            {(preview.items || []).slice(0, 15).map((t) => (
              <Link key={t.id} to={`/trade/${t.id}`}>{t.ticker || t.asset_name} · {t.member}<span className="src"> · {t.alert_reason}</span></Link>
            ))}
            {!preview.items?.length && <p className="muted">No recent trades match this rule.</p>}
          </div>
        </div>
      )}

      <h2>Your rules</h2>
      {rules.length === 0 ? <p className="muted">No rules yet.</p> : (
        <div className="panel" style={{ padding: 0 }}>
          <table>
            <thead><tr><th>Name</th><th>Type</th><th>Params</th><th>Channels</th><th>Last fired</th><th></th></tr></thead>
            <tbody>
              {rules.map((r) => (
                <tr key={r.id}>
                  <td>{r.name}</td>
                  <td><span className="tag src">{r.rule_type}</span></td>
                  <td className="muted">{Object.entries(r.params || {}).map(([k, v]) => `${k}=${v}`).join(', ') || '—'}</td>
                  <td className="muted">{(r.channels || []).map((c) => c.type).join(', ') || 'ntfy'}</td>
                  <td className="muted nowrap">{r.last_fired_at ? r.last_fired_at.slice(0, 10) : '—'}</td>
                  <td><button className="btn-sm" onClick={() => del(r.id)}>Delete</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

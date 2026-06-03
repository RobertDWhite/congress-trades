// Provenance badge for the public credibility layer. Accepts a dossier provenance object
// ({label, kind, detail, primary}) — or pass label/kind directly for use elsewhere.
export default function SourceBadge({ source, label, kind = 'other', detail, primary = false }) {
  const s = source || { label, kind, detail, primary }
  if (!s.label) return null
  return (
    <span className={`prov-badge prov-${s.kind || 'other'}`} title={s.detail || ''}>
      {s.primary && <span className="prov-check" aria-hidden="true">✓ </span>}
      {s.label}
    </span>
  )
}

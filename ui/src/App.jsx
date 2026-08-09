import { lazy, Suspense } from 'react'
import { Link, Navigate, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import GlobalSearch from './components/GlobalSearch.jsx'
import { WatchlistProvider } from './watchctx.jsx'

// Grouped nav: a top-level label that reveals a dropdown on hover/focus. Highlights when one of
// its routes is active. Keeps the top bar to a handful of items instead of ~20 wrapping links.
function NavGroup({ label, items, pathname }) {
  const active = items.some((it) => pathname === it.to || pathname.startsWith(it.to + '/'))
  return (
    <div className="navgroup">
      <button type="button" className={`navgroup-label ${active ? 'active' : ''}`}>
        {label} <span className="caret" aria-hidden="true">▾</span>
      </button>
      <div className="navgroup-menu">
        {items.map((it) => <NavLink key={it.to} to={it.to}>{it.label}</NavLink>)}
      </div>
    </div>
  )
}

const Dashboard = lazy(() => import('./pages/Dashboard.jsx'))
const Feed = lazy(() => import('./pages/Feed.jsx'))
const Ideas = lazy(() => import('./pages/Ideas.jsx'))
const Leaderboard = lazy(() => import('./pages/Leaderboard.jsx'))
const Members = lazy(() => import('./pages/Members.jsx'))
const MemberDetail = lazy(() => import('./pages/MemberDetail.jsx'))
const Tickers = lazy(() => import('./pages/Tickers.jsx'))
const TickerDetail = lazy(() => import('./pages/TickerDetail.jsx'))
const Signals = lazy(() => import('./pages/Signals.jsx'))
const DisclosureLag = lazy(() => import('./pages/DisclosureLag.jsx'))
const Strategies = lazy(() => import('./pages/Strategies.jsx'))
const Portfolio = lazy(() => import('./pages/Portfolio.jsx'))
const Watchlist = lazy(() => import('./pages/Watchlist.jsx'))
const Sources = lazy(() => import('./pages/Sources.jsx'))
const Status = lazy(() => import('./pages/Status.jsx'))
const Committees = lazy(() => import('./pages/Committees.jsx'))
const Reconciliation = lazy(() => import('./pages/Reconciliation.jsx'))
const PolicyContext = lazy(() => import('./pages/PolicyContext.jsx'))
const Research = lazy(() => import('./pages/Research.jsx'))
const TradeDossier = lazy(() => import('./pages/TradeDossier.jsx'))
const Options = lazy(() => import('./pages/Options.jsx'))
const Discover = lazy(() => import('./pages/Discover.jsx'))
const Compare = lazy(() => import('./pages/Compare.jsx'))
const Alerts = lazy(() => import('./pages/Alerts.jsx'))
const Methodology = lazy(() => import('./pages/Methodology.jsx'))

export default function App() {
  const publicSite = window.CONGRESS_TRADES_CONFIG?.publicSite === true
  const { pathname } = useLocation()

  return (
    <WatchlistProvider>
      <header className="topbar">
        <span className="brand">🏛️ Congress Trades</span>
        <nav>
          <NavLink to="/" end className="navlink">Dashboard</NavLink>
          <NavGroup label="Trades" pathname={pathname} items={[
            { to: '/feed', label: 'Feed' },
            { to: '/discover', label: 'Discover' },
            { to: '/options', label: 'Options' },
            { to: '/research', label: 'Unusual activity' },
            { to: '/signals', label: 'Signals' },
            { to: '/ideas', label: 'Ideas' },
          ]} />
          <NavGroup label="Analysis" pathname={pathname} items={[
            { to: '/strategies', label: 'Strategies' },
            { to: '/leaderboard', label: 'Leaderboard' },
            { to: '/lag', label: 'Disclosure lag' },
            { to: '/policy', label: 'Policy context' },
            { to: '/committees', label: 'Committees' },
          ]} />
          <NavGroup label="Browse" pathname={pathname} items={[
            { to: '/members', label: 'Members' },
            { to: '/compare', label: 'Compare' },
            { to: '/tickers', label: 'Tickers' },
          ]} />
          <NavGroup label="You" pathname={pathname} items={[
            { to: '/watchlist', label: 'Watchlist' },
            { to: '/alerts', label: 'Alerts' },
            ...(!publicSite ? [{ to: '/portfolio', label: 'Portfolio' }] : []),
          ]} />
          <NavGroup label="About" pathname={pathname} items={[
            { to: '/sources', label: 'Sources' },
            { to: '/about', label: 'Methodology' },
            { to: '/status', label: 'Status' },
          ]} />
        </nav>
        <GlobalSearch />
      </header>
      <main>
        <Suspense fallback={<div className="loading">Loading…</div>}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/ideas" element={<Ideas />} />
            <Route path="/feed" element={<Feed />} />
            <Route path="/signals" element={<Signals />} />
            <Route path="/research" element={<Research />} />
            <Route path="/trade/:id" element={<TradeDossier />} />
            <Route path="/options" element={<Options />} />
            <Route path="/discover" element={<Discover />} />
            <Route path="/compare" element={<Compare />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/about" element={<Methodology />} />
            <Route path="/lag" element={<DisclosureLag />} />
            <Route path="/strategies" element={<Strategies />} />
            <Route path="/portfolio" element={publicSite ? <Navigate to="/" replace /> : <Portfolio />} />
            <Route path="/leaderboard" element={<Leaderboard />} />
            <Route path="/policy" element={<PolicyContext />} />
            <Route path="/committees" element={<Committees />} />
            <Route path="/members" element={<Members />} />
            <Route path="/members/:id" element={<MemberDetail />} />
            <Route path="/tickers" element={<Tickers />} />
            <Route path="/tickers/:symbol" element={<TickerDetail />} />
            <Route path="/watchlist" element={<Watchlist />} />
            <Route path="/sources" element={<Sources />} />
            <Route path="/status" element={<Status />} />
            <Route path="/reconciliation" element={<Reconciliation />} />
          </Routes>
        </Suspense>
      </main>
      <footer className="site-disclaimer">
        <strong>Research project — not an investment strategy, and not investment advice.</strong>{' '}
        This site exists to test whether STOCK Act disclosures can be parsed reliably from the primary
        sources. It is not built to trade on and should not be used to make financial decisions. Nothing
        here is a recommendation to buy or sell any security, and the author is not a licensed financial
        advisor. Disclosures are lagged up to <strong>45 days</strong>, figures are estimates derived in
        part from OCR and inferred tickers, and any backtest shown is hypothetical, in-sample, and
        excludes costs and slippage. Past performance does not predict future results.{' '}
        <Link to="/about">Methodology &amp; data</Link>
      </footer>
    </WatchlistProvider>
  )
}

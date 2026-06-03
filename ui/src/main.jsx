import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.jsx'
import './styles.css'

// Top-level guard: without this, any uncaught render error (or a failed lazy-chunk load) unmounts
// the whole tree and leaves a blank navy screen. Now it shows the error and keeps the page usable.
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }
  static getDerivedStateFromError(error) {
    return { error }
  }
  componentDidCatch(error, info) {
    console.error('Render error:', error, info)
  }
  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 24, color: '#e6edf3', fontFamily: '-apple-system, Segoe UI, Roboto, sans-serif', maxWidth: 900, margin: '0 auto' }}>
          <h1>Something went wrong</h1>
          <p style={{ color: '#8b949e' }}>The page hit an error while rendering. Reload to try again — if it persists, the message below is the cause.</p>
          <pre style={{ whiteSpace: 'pre-wrap', background: '#161b22', border: '1px solid #30363d', borderRadius: 8, padding: 12, color: '#f85149' }}>
            {String(this.state.error && (this.state.error.stack || this.state.error.message || this.state.error))}
          </pre>
          <button onClick={() => window.location.reload()} style={{ marginTop: 12, padding: '8px 14px', background: '#161b22', color: '#e6edf3', border: '1px solid #30363d', borderRadius: 6, cursor: 'pointer' }}>
            Reload
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </BrowserRouter>
  </React.StrictMode>,
)

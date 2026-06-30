/**
 * CodeScan — Main React App (Premium UI Refactor)
 * ===============================================
 * - Uses classnames instead of inline styles for cleaner code & better hover effects.
 * - Integrates Monaco Editor and ReactMarkdown.
 */

import { useState, useEffect } from "react";
import {
  BrowserRouter,
  Routes,
  Route,
  Link,
  Navigate,
  useNavigate,
} from "react-router-dom";
import { register, login, logout, analyzeCode, getScans } from "./api";
import ReactMarkdown from "react-markdown";
import Editor from "@monaco-editor/react";
import "./App.css";

// ========================================================================== //
// APP ROOT
// ========================================================================== //

export default function App() {
  const [user, setUser] = useState(null);

  return (
    <BrowserRouter>
      <div className="app-container">
        <Navbar user={user} onLogout={() => setUser(null)} />
        <div className="main-content">
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/login" element={<LoginPage onLogin={setUser} />} />
            <Route path="/register" element={<RegisterPage onRegister={setUser} />} />
            <Route path="/history" element={user ? <HistoryPage /> : <Navigate to="/login" />} />
            <Route path="*" element={<Navigate to="/" />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  );
}

// ========================================================================== //
// NAVBAR
// ========================================================================== //

function Navbar({ user, onLogout }) {
  async function handleLogout() {
    try { await logout(); } catch { }
    onLogout();
  }

  return (
    <nav className="navbar">
      <Link to="/" className="navbar-logo">🔍 CodeScan</Link>
      <div className="navbar-links">
        <Link to="/" className="nav-link">Analyze</Link>
        {user && <Link to="/history" className="nav-link">History</Link>}
        {user ? (
          <>
            <span className="nav-user">👤 {user.username}</span>
            <button onClick={handleLogout} className="btn btn-ghost">Logout</button>
          </>
        ) : (
          <>
            <Link to="/login" className="nav-link">Login</Link>
            <Link to="/register" className="nav-link">Register</Link>
          </>
        )}
      </div>
    </nav>
  );
}

// ========================================================================== //
// HOME PAGE (Analyzer)
// ========================================================================== //

function HomePage() {
  const [code, setCode] = useState(DEFAULT_CODE);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleAnalyze() {
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const res = await analyzeCode(code);
      setResult(res.data);
    } catch (err) {
      setError(err.response?.data?.error || "Analysis failed. Is the backend running?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="analyzer-layout">
      {/* LEFT PANEL: Code Editor */}
      <div className="editor-panel">
        <div className="editor-wrapper">
          <div className="editor-header">
            <span>🐍 python</span>
          </div>
          <Editor
            height="100%" /* Fills the 50% screen width dynamically */
            defaultLanguage="python"
            language="python"
            value={code}
            theme="light"
            onChange={(value) => setCode(value || "")}
            options={{ minimap: { enabled: false }, fontSize: "14px", scrollBeyondLastLine: false, automaticLayout: true }}
          />
        </div>

        <div className="action-row">
          <button onClick={handleAnalyze} disabled={loading || !code.trim()} className="btn btn-primary">
            {loading ? "Analyzing..." : "🔍 Analyze Code"}
          </button>
          <button onClick={() => { setCode(""); setResult(null); setError(""); }} className="btn btn-secondary">
            Clear
          </button>
        </div>

        {error && <div className="error-box" style={{ marginTop: "16px" }}>{error}</div>}
      </div>

      {/* RIGHT PANEL: Results */}
      <div className="results-panel">
        {result ? (
          <ResultPanel result={result} />
        ) : (
          <div className="results-empty">
            <div className="results-empty-icon">📊</div>
            <h3>Ready for Analysis</h3>
            <p>Write your code on the left, then click "Analyze" to see the complexity and issues appear here.</p>
          </div>
        )}
      </div>
    </div>
  );
}

// ========================================================================== //
// RESULT PANEL
// ========================================================================== //

function ResultPanel({ result }) {
  const sevClass = (sev) => sev.toLowerCase();

  return (
    <>
      {/* STICKY HEADER: Complexity stays visible at the top */}
      <div className="results-header">
        <span className="badge-complexity">{result.complexity}</span>
        <span className="badge-duration">⏱ {result.analysis_duration_ms}ms</span>
      </div>

      {/* SCROLLABLE BODY: Issues & AI Suggestions */}
      <div className="results-body">
        {result.issues.length === 0 ? (
          <div className="empty-state">
            <h3>✅ No performance issues detected!</h3>
            <p>Your code runs efficiently based on algorithmic complexity.</p>
          </div>
        ) : (
          <div>
            {result.issues.map((issue, i) => (
              <div key={i} className={`issue-card severity-${sevClass(issue.severity)}`}>
                <div className="issue-header">
                  <span className={`severity-tag ${sevClass(issue.severity)}`}>{issue.severity}</span>
                  <span className="issue-type">{issue.type}</span>
                  <span className="issue-line">Line {issue.line}</span>
                </div>
                <div className="issue-message">{issue.message}</div>
              </div>
            ))}
          </div>
        )}

        {result.groq_explanation && (
          <div className="ai-box">
            {/* Updated Text Here */}
            <div className="ai-header">💡 CodeScan Suggestion and Correction Fix</div>
            <div className="ai-content">
              <ReactMarkdown>{result.groq_explanation}</ReactMarkdown>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

// ========================================================================== //
// LOGIN / REGISTER PAGES
// ========================================================================== //

function LoginPage({ onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const navigate = useNavigate();

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    try {
      const res = await login({ username, password });
      onLogin(res.data.user);
      navigate("/");
    } catch (err) {
      setError(err.response?.data?.error || "Login failed.");
    }
  }

  return (
    <div className="auth-container">
      <h2 className="auth-title">Login to CodeScan</h2>
      {error && <div className="error-box">{error}</div>}
      <form onSubmit={handleSubmit}>
        <div className="input-group">
          <input className="input" placeholder="Username" value={username} onChange={(e) => setUsername(e.target.value)} />
        </div>
        <div className="input-group">
          <input className="input" type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        <button type="submit" className="btn btn-primary btn-block">Login</button>
      </form>
      <div className="switch-text">No account? <Link to="/register">Register</Link></div>
    </div>
  );
}

function RegisterPage({ onRegister }) {
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const navigate = useNavigate();

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    try {
      const res = await register({ username, email, password });
      onRegister(res.data.user);
      navigate("/");
    } catch (err) {
      setError(err.response?.data?.error || "Registration failed.");
    }
  }

  return (
    <div className="auth-container">
      <h2 className="auth-title">Create an Account</h2>
      {error && <div className="error-box">{error}</div>}
      <form onSubmit={handleSubmit}>
        <div className="input-group">
          <input className="input" placeholder="Username" value={username} onChange={(e) => setUsername(e.target.value)} />
        </div>
        <div className="input-group">
          <input className="input" type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="input-group">
          <input className="input" type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        <button type="submit" className="btn btn-primary btn-block">Register</button>
      </form>
      <div className="switch-text">Already have an account? <Link to="/login">Login</Link></div>
    </div>
  );
}

// ========================================================================== //
// HISTORY PAGE
// ========================================================================== //

function HistoryPage() {
  const [scans, setScans] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    getScans()
      .then((res) => setScans(res.data.scans))
      .catch(() => setError("Could not load history."))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="empty-state">Loading history...</div>;
  if (error) return <div className="error-box">{error}</div>;

  return (
    <div>
      <h1 className="page-title">Your Scan History</h1>
      <p className="page-subtitle">A record of your previously analyzed code snippets.</p>
      
      {scans.length === 0 ? (
        <div className="empty-state">
          <h3>No scans yet!</h3>
          <p>Go to the Analyze page and scan some code.</p>
        </div>
      ) : (
        <div>
          {scans.map((scan) => (
            <div key={scan.id} className="history-item">
              <div style={{display: 'flex', justifyContent: 'space-between', marginBottom: '12px'}}>
                <span className="badge-complexity">{scan.complexity_score}</span>
                <span className="badge-duration">{new Date(scan.created_at).toLocaleString()}</span>
              </div>
              <pre style={{background: '#f9fafb', padding: '12px', borderRadius: '6px', fontSize: '13px', color: '#4b5563', overflowX: 'auto'}}>
                {scan.code_preview}
              </pre>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ========================================================================== //
// CONSTANTS
// ========================================================================== //

const DEFAULT_CODE = `def find_pairs(items):
    pairs = []
    for a in items:
        for b in items:
            if a in items:
                pairs.append((a, b))
    return pairs`;

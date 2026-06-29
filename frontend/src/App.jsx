/**
 * CodeScan — Main React App
 * =========================
 * Self-contained app with:
 *   - React Router (5 routes)
 *   - Auth state (login/register/logout)
 *   - Code analyzer (textarea + results)
 *   - Scan history
 *
 * Auth state is lifted to <App> and passed to pages via props.
 * Session is maintained by the Flask cookie (see api.js withCredentials).
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
import Editor, { useMonaco } from "@monaco-editor/react";

// ========================================================================== //
// APP ROOT — holds auth state + router
// ========================================================================== //

export default function App() {
  const [user, setUser] = useState(null);

  return (
    <BrowserRouter>
      <div style={styles.page}>
        <Navbar user={user} onLogout={() => setUser(null)} />
        <div style={styles.content}>
          <Routes>
            <Route path="/" element={<HomePage user={user} />} />
            <Route
              path="/login"
              element={<LoginPage onLogin={setUser} />}
            />
            <Route
              path="/register"
              element={<RegisterPage onRegister={setUser} />}
            />
            <Route
              path="/history"
              element={
                user ? <HistoryPage user={user} /> : <Navigate to="/login" />
              }
            />
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
    try {
      await logout();
    } catch {
      // ignore — clearing local state regardless
    }
    onLogout();
  }

  return (
    <nav style={styles.nav}>
      <Link to="/" style={styles.logo}>
        🔍 CodeScan
      </Link>
      <div style={styles.navLinks}>
        <Link to="/" style={styles.navLink}>Analyze</Link>
        {user && <Link to="/history" style={styles.navLink}>History</Link>}
        {user ? (
          <>
            <span style={styles.navUser}>👤 {user.username}</span>
            <button onClick={handleLogout} style={styles.btnSm}>Logout</button>
          </>
        ) : (
          <>
            <Link to="/login" style={styles.navLink}>Login</Link>
            <Link to="/register" style={styles.navLink}>Register</Link>
          </>
        )}
      </div>
    </nav>
  );
}

// ========================================================================== //
// HOME PAGE — the code analyzer
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
      const msg = err.response?.data?.error || "Analysis failed. Is the backend running?";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <h1 style={styles.h1}>Static Python Code Analyzer</h1>
      <p style={styles.subtitle}>
        Paste your Python code below. We walk the AST — your code is never executed.
      </p>

      <div style={{ border: "1px solid #c4d4df", borderRadius: "8px", overflow: "hidden" }}>
        <Editor
          height="300px"
          defaultLanguage="python"
          language="python"
          value={code}
          theme="vs-dark"
          onChange={(value) => setCode(value || "")}
          options={{
            minimap: { enabled: false },
            fontSize: "14px",
            scrollBeyondLastLine: false,
            wordWrap: "on",
            tabSize: 4,
            automaticLayout: true,
          }}
        />
      </div>

      <div style={styles.btnRow}>
        <button
          onClick={handleAnalyze}
          disabled={loading || !code.trim()}
          style={styles.btnPrimary}
        >
          {loading ? "Analyzing..." : "🔍 Analyze Code"}
        </button>
        <button onClick={() => { setCode(""); setResult(null); setError(""); }} style={styles.btnGhost}>
          Clear
        </button>
      </div>

      {error && <div style={styles.errorBox}>{error}</div>}

      {result && <ResultPanel result={result} />}
    </div>
  );
}

// ========================================================================== //
// RESULT PANEL — shows complexity, issues, and AI explanation
// ========================================================================== //

function ResultPanel({ result }) {
  return (
    <div style={styles.resultBox}>
      <div style={styles.resultHeader}>
        <span style={styles.complexityBadge}>{result.complexity}</span>
        <span style={styles.issueCount}>
          {result.issues.length} issue{result.issues.length !== 1 ? "s" : ""} found
        </span>
        <span style={styles.duration}>⏱ {result.analysis_duration_ms}ms</span>
      </div>

      {result.ai_status === "unavailable" ? (
        <div style={styles.aiBadge}>🤖 AI suggestions unavailable (still works!)</div>
      ) : (
        <div style={styles.aiBadgeOk}>🤖 AI suggestions ready</div>
      )}

      {result.issues.length === 0 ? (
        <div style={styles.noIssues}>✅ No performance issues detected!</div>
      ) : (
        <div>
          {result.issues.map((issue, i) => (
            <IssueCard key={i} issue={issue} />
          ))}
        </div>
      )}

      {result.groq_explanation && (
        <div style={styles.groqBox}>
          <h3 style={styles.h3}>🤖 AI Explanation</h3>
          <div className="markdown-body" style={styles.markdownBody}>
            <ReactMarkdown
              components={{
                h1: ({node, ...props}) => <h3 style={{marginTop: '12px', marginBottom: '6px', color: '#0b3d66'}} {...props} />,
                h2: ({node, ...props}) => <h3 style={{marginTop: '12px', marginBottom: '6px', color: '#0b3d66'}} {...props} />,
                h3: ({node, ...props}) => <h4 style={{marginTop: '10px', marginBottom: '4px', color: '#0b3d66'}} {...props} />,
                p: ({node, ...props}) => <p style={{margin: '8px 0', lineHeight: '1.6', fontSize: '14px'}} {...props} />,
                ul: ({node, ...props}) => <ul style={{margin: '8px 0', paddingLeft: '20px'}} {...props} />,
                ol: ({node, ...props}) => <ol style={{margin: '8px 0', paddingLeft: '20px'}} {...props} />,
                li: ({node, ...props}) => <li style={{margin: '4px 0', fontSize: '14px', lineHeight: '1.6'}} {...props} />,
                code: ({inline, className, children, ...props}) => 
                  inline ? (
                    <code style={{ background: '#e1e8ef', padding: '2px 6px', borderRadius: '4px', fontFamily: 'monospace', fontSize: '13px', color: '#d64545' }} {...props}>{children}</code>
                  ) : (
                    <pre style={{ background: '#0b3d66', color: '#fff', padding: '12px', borderRadius: '6px', overflowX: 'auto', margin: '10px 0' }}>
                      <code style={{ fontFamily: "'Fira Code', monospace", fontSize: '13px' }} {...props}>{children}</code>
                    </pre>
                  ),
              }}
            >
              {result.groq_explanation}
            </ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  );
}

function IssueCard({ issue }) {
  const sev = (issue.severity || "").toLowerCase();
  const color = sev === "high" ? "#d64545" : sev === "med" ? "#e08a1e" : "#2e9e5b";

  return (
    <div style={{ ...styles.issueCard, borderLeftColor: color }}>
      <div style={styles.issueTop}>
        <span style={{ ...styles.sevTag, backgroundColor: color }}>
          {issue.severity}
        </span>
        <strong>{issue.type}</strong>
        <span style={styles.lineNo}>Line {issue.line}</span>
      </div>
      <p style={styles.issueMsg}>{issue.message}</p>
    </div>
  );
}

// ========================================================================== //
// LOGIN PAGE
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
    <div style={styles.authBox}>
      <h2 style={styles.h2}>Login</h2>
      {error && <div style={styles.errorBox}>{error}</div>}
      <form onSubmit={handleSubmit}>
        <input style={styles.input} placeholder="Username" value={username}
          onChange={(e) => setUsername(e.target.value)} />
        <input style={styles.input} type="password" placeholder="Password" value={password}
          onChange={(e) => setPassword(e.target.value)} />
        <button type="submit" style={styles.btnPrimary}>Login</button>
      </form>
      <p style={styles.switchLink}>
        No account? <Link to="/register">Register</Link>
      </p>
    </div>
  );
}

// ========================================================================== //
// REGISTER PAGE
// ========================================================================== //

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
    <div style={styles.authBox}>
      <h2 style={styles.h2}>Create Account</h2>
      {error && <div style={styles.errorBox}>{error}</div>}
      <form onSubmit={handleSubmit}>
        <input style={styles.input} placeholder="Username" value={username}
          onChange={(e) => setUsername(e.target.value)} />
        <input style={styles.input} type="email" placeholder="Email" value={email}
          onChange={(e) => setEmail(e.target.value)} />
        <input style={styles.input} type="password" placeholder="Password" value={password}
          onChange={(e) => setPassword(e.target.value)} />
        <button type="submit" style={styles.btnPrimary}>Register</button>
      </form>
      <p style={styles.switchLink}>
        Already have an account? <Link to="/login">Login</Link>
      </p>
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

  if (loading) return <p>Loading history...</p>;
  if (error) return <div style={styles.errorBox}>{error}</div>;

  return (
    <div>
      <h1 style={styles.h1}>Scan History</h1>
      {scans.length === 0 ? (
        <p style={styles.subtitle}>No scans yet. Go analyze some code!</p>
      ) : (
        <div>
          {scans.map((scan) => (
            <div key={scan.id} style={styles.scanRow}>
              <div style={styles.scanLeft}>
                <span style={styles.complexityBadgeSm}>{scan.complexity_score}</span>
                <span style={styles.issueCount}>{scan.issue_count} issues</span>
                <span style={styles.duration}>Scan #{scan.id}</span>
              </div>
              <pre style={styles.preview}>{scan.code_preview}</pre>
              <span style={styles.date}>{scan.created_at?.slice(0, 19).replace("T", " ")}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ========================================================================== //
// INLINE STYLES
// ========================================================================== //

const DEFAULT_CODE = `def find_pairs(items):
    pairs = []
    for a in items:
        for b in items:
            if a in items:
                pairs.append((a, b))
    return pairs`;

const styles = {
  page: {
    fontFamily: "'Segoe UI', system-ui, sans-serif",
    minHeight: "100vh",
    background: "#f4f6f9",
    color: "#1f2933",
  },
  nav: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "12px 32px",
    background: "#0b3d66",
    color: "#fff",
  },
  logo: { color: "#fff", textDecoration: "none", fontSize: "20px", fontWeight: "bold" },
  navLinks: { display: "flex", gap: "16px", alignItems: "center" },
  navLink: { color: "#cfe3ef", textDecoration: "none", fontSize: "14px" },
  navUser: { color: "#fff", fontSize: "14px" },
  content: { maxWidth: "900px", margin: "0 auto", padding: "32px 24px" },
  h1: { fontSize: "28px", marginBottom: "8px", color: "#0b3d66" },
  h2: { fontSize: "24px", marginBottom: "16px", color: "#0b3d66" },
  h3: { fontSize: "18px", marginBottom: "8px" },
  subtitle: { color: "#5a6b78", marginBottom: "20px", fontSize: "15px" },
  btnRow: { display: "flex", gap: "12px", marginTop: "12px" },
  btnPrimary: {
    padding: "10px 24px",
    background: "#15a0c4",
    color: "#fff",
    border: "none",
    borderRadius: "6px",
    fontSize: "15px",
    cursor: "pointer",
    fontWeight: "bold",
  },
  btnGhost: {
    padding: "10px 24px",
    background: "transparent",
    color: "#5a6b78",
    border: "1px solid #c4d4df",
    borderRadius: "6px",
    fontSize: "15px",
    cursor: "pointer",
  },
  btnSm: {
    padding: "6px 14px",
    background: "transparent",
    color: "#fff",
    border: "1px solid #cfe3ef",
    borderRadius: "4px",
    cursor: "pointer",
    fontSize: "13px",
  },
  resultBox: { marginTop: "24px", background: "#fff", borderRadius: "10px", padding: "20px", border: "1px solid #e1e8ef" },
  resultHeader: { display: "flex", gap: "12px", alignItems: "center", marginBottom: "16px", flexWrap: "wrap" },
  complexityBadge: { background: "#0b3d66", color: "#fff", padding: "6px 14px", borderRadius: "20px", fontWeight: "bold", fontSize: "14px" },
  complexityBadgeSm: { background: "#0b3d66", color: "#fff", padding: "3px 10px", borderRadius: "12px", fontSize: "12px" },
  issueCount: { color: "#5a6b78", fontSize: "14px" },
  duration: { color: "#8a99a6", fontSize: "13px", marginLeft: "auto" },
  aiBadge: { background: "#fff6ec", color: "#946014", padding: "8px 12px", borderRadius: "6px", fontSize: "13px", marginBottom: "12px" },
  aiBadgeOk: { background: "#eafaf0", color: "#1a7a43", padding: "8px 12px", borderRadius: "6px", fontSize: "13px", marginBottom: "12px" },
  noIssues: { textAlign: "center", padding: "24px", color: "#2e9e5b", fontSize: "16px" },
  issueCard: { background: "#f8fafc", borderLeft: "4px solid #ccc", borderRadius: "6px", padding: "12px 16px", marginBottom: "10px" },
  issueTop: { display: "flex", gap: "10px", alignItems: "center", marginBottom: "6px" },
  sevTag: { color: "#fff", padding: "2px 8px", borderRadius: "4px", fontSize: "11px", fontWeight: "bold" },
  lineNo: { color: "#8a99a6", fontSize: "13px", marginLeft: "auto" },
  issueMsg: { fontSize: "14px", color: "#3a4a56", margin: "0" },
  groqBox: { marginTop: "16px", background: "#f0f7fb", borderRadius: "8px", padding: "16px", border: "1px solid #cfe3ef" },
  groqText: { whiteSpace: "pre-wrap", fontSize: "14px", lineHeight: "1.6", fontFamily: "'Segoe UI', sans-serif", margin: "0" },
  authBox: { maxWidth: "400px", margin: "60px auto", background: "#fff", padding: "32px", borderRadius: "10px", border: "1px solid #e1e8ef" },
  input: { width: "100%", padding: "12px", marginBottom: "12px", border: "1px solid #c4d4df", borderRadius: "6px", fontSize: "15px", boxSizing: "border-box" },
  errorBox: { background: "#fde8e8", color: "#a02828", padding: "10px 14px", borderRadius: "6px", marginBottom: "12px", fontSize: "14px" },
  switchLink: { textAlign: "center", marginTop: "16px", color: "#5a6b78", fontSize: "14px" },
  scanRow: { background: "#fff", borderRadius: "8px", padding: "16px", marginBottom: "12px", border: "1px solid #e1e8ef" },
  scanLeft: { display: "flex", gap: "12px", alignItems: "center", marginBottom: "8px" },
  preview: { background: "#f8fafc", padding: "8px 12px", borderRadius: "6px", fontSize: "12px", fontFamily: "monospace", overflow: "hidden", whiteSpace: "pre-wrap", maxHeight: "60px", margin: "0 0 8px 0" },
  date: { color: "#8a99a6", fontSize: "12px" },
};

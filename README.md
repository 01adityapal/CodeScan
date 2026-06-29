<div align="center">

# 🔍 CodeScan

### Static Python Code Analysis Engine

**Walks the Python AST to detect hidden complexity — no code execution, AI-powered explanations, production-grade security.**

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.1-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)](https://react.dev)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Neon-4169E1?logo=postgresql&logoColor=white)](https://neon.tech)
[![AWS](https://img.shields.io/badge/AWS-Deployed-FF9900?logo=amazonaws&logoColor=white)](https://aws.amazon.com)

</div>

---

## 📖 The Problem

Python developers write code with hidden O(n²) complexity, wrong data-structure choices, and unoptimized recursion every day. Compilers don't catch these. Linters like Pylint flag syntax and style — not logic-level performance problems.

## 💡 The Solution

**CodeScan** is a static analysis tool that reads your Python code using the built-in `ast` module, detects real algorithmic issues, and uses Groq AI (Llama 3.1) to explain them in plain English like a senior developer reviewing your PR.

### 🛡️ The Golden Rule (Security by Design)
> **CodeScan NEVER executes user code.** It reads `os.system("rm -rf /")` as a harmless text node in a syntax tree. It is immune to Remote Code Execution (RCE) by architecture, not by patch.

---

## ✨ Key Features

### 1. Honest Complexity Detection
The AST engine walks the syntax tree and flags real issues:
- **Nested Loops** → `Likely O(n²)` *(only when iterating over variables, not `range(10)`)*
- **Inefficient Lookups** → `x in my_list` inside a loop *(only flags lists/tuples, not sets/dicts)*
- **Unoptimized Recursion** → Self-calling functions missing `@lru_cache`
- **Blocking I/O in Loops** → `requests.get()` or `time.sleep()` inside `for` loops

### 2. AI Explanations with Circuit Breaker
- Groq AI explains *why* the code is slow and *how* to fix it.
- Wrapped in a **Circuit Breaker** (`pybreaker`): if Groq fails 3 times, it stops trying for 60 seconds.
- **Graceful Degradation:** If Groq is down, the app returns AST results anyway with `ai_status: "unavailable"`. The product never breaks.

### 3. Production-Grade Security
- **Two-Layer Login Defence:** IP-based rate limiting (Flask-Limiter) + Account lockout after 5 failures.
- **IDOR Protection:** Scan history is strictly filtered by `user_id`.
- **SQL Injection Safe:** 100% SQLAlchemy ORM with dynamic `ORDER BY` whitelisting.
- **Data Minimization:** Only the first 500 chars of scanned code are stored as a preview.

---

## 🏗 System Architecture

```text
User Browser (React + Monaco Editor)
      │ (HTTPS)
      ▼
CloudFront CDN ─────────────────┐
      ├── /* behavior     →  S3 (React Static Files)
      ├── /api/* behavior →  EC2 (Flask Backend)
                                   │
                              Nginx (Reverse Proxy)
                                   │
                              Gunicorn (WSGI, Multi-worker)
                                   │
                              Flask App (localhost:5000)
                                   │
            ┌──────────────────────┼──────────────────────┐
            ▼                      ▼                      ▼
      Redis (Limiter)       AST Engine              Groq API
                            (Complexity)            (+ Circuit Breaker)
            │                      │                      │
            └──────────────────────┼──────────────────────┘
                                   ▼
                        Neon PostgreSQL (Scan History)
```

---

## 💻 Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Frontend** | React 18, Vite, Monaco Editor | VS Code-style input, results dashboard |
| **Backend** | Python, Flask, Gunicorn | REST API, AST analysis, WSGI server |
| **Database** | PostgreSQL (Neon) | Scan history, user accounts |
| **Cache/Security** | Redis | Rate limiting backend (prod), Caching |
| **AI** | Groq API (Llama-3.1-8b) | Plain English explanations |
| **Auth** | Flask-Login, bcrypt | Session management, password hashing |

---

## 🚀 Local Development Setup

### Prerequisites
- Python 3.10+
- Node.js 18+
- A free [Groq API Key](https://console.groq.com/keys)

### 1. Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate
# Activate (Mac/Linux)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your GROQ_API_KEY

# Run the server
flask --app app run --debug
```
The backend will be running at `http://localhost:5000`.

### 2. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start dev server
npm run dev
```
The frontend will be running at `http://localhost:5173`.

---

## 📡 API Reference

### `POST /api/v1/analyze`
Analyzes Python code and returns complexity, issues, and AI explanation.

**Request Body:**
```json
{
  "code": "for i in items:\n    for j in items:\n        print(i, j)"
}
```

**Response (200 OK):**
```json
{
  "status": "success",
  "complexity": "Likely O(n^2)",
  "issues": [
    {
      "line": 2,
      "type": "Nested Loop",
      "severity": "High",
      "message": "Nested loop over variables. Likely O(n^2)."
    }
  ],
  "groq_explanation": "Consider using a hashmap to flatten this to O(n)...",
  "ai_status": "available",
  "analysis_duration_ms": 143
}
```

### Auth & History Endpoints
- `POST /api/v1/auth/register` - Create account
- `POST /api/v1/auth/login` - Login (sets session cookie)
- `POST /api/v1/auth/logout` - Logout
- `GET /api/v1/scans` - Get user's scan history (Auth required)
- `GET /api/v1/scans/:id` - Get specific scan details (Auth required, IDOR-safe)
- `GET /health` - Health check endpoint

---

## 🎓 Interview Q&A

**Q: How do you protect against malicious code?**
> We never execute it. The `ast` module only reads source text and builds a tree. Security by design.

**Q: What if the Groq API goes down?**
> Groq is an enhancement, not a dependency. A circuit breaker stops calling it after 3 failures, and we return `ai_status: "unavailable"`. AST results always return.

**Q: Why Gunicorn and not just Flask?**
> Flask's dev server is single-threaded. Gunicorn handles multiple worker processes for concurrency.

**Q: How is your complexity estimate honest?**
> I only report O(n²) when loops iterate over variables, never over `range(10)` which is O(1). When I can't prove a container's type, I stay silent.

---

<div align="center">
Made with Flask, React, and a lot of AST traversal.
</div>

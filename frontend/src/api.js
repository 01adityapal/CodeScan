/**
 * CodeScan API Client
 * ===================
 * A thin wrapper around axios that talks to the Flask backend.
 *
 * Critical detail:
 *   withCredentials: true  ->  tells the browser to SEND and STORE the
 *   Flask session cookie. Without this, login would "work" but every
 *   subsequent request would be treated as anonymous (the bug we saw
 *   when testing with PowerShell).
 *
 * All endpoints return Promises. Route handlers / React components
 * will .then() or await these and handle errors via try/catch.
 */

import axios from "axios";

// Base URL of the Flask backend.
// - Development: localhost:5000 (different port than Vite's 5173)
// - Production:  empty string = relative URL (same CloudFront origin as React)
const BASE_URL = import.meta.env.PROD
  ? ""
  : import.meta.env.VITE_API_URL || "http://localhost:5000";

// One shared axios instance configured for cookies + JSON.
const api = axios.create({
  baseURL: `${BASE_URL}/api/v1`,
  withCredentials: true, // <-- REQUIRED for session cookies
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 30000, // 30s — Groq can be slow on first call
});

// ---------------------------------------------------------------------------
// Auth endpoints
// ---------------------------------------------------------------------------

/**
 * Register a new account.
 * @param {{username: string, email: string, password: string}} data
 */
export function register(data) {
  return api.post("/auth/register", data);
}

/**
 * Log in. Flask sets the session cookie in the response.
 * @param {{username: string, password: string}} data
 */
export function login(data) {
  return api.post("/auth/login", data);
}

/** Log out (clears the server-side session). */
export function logout() {
  return api.post("/auth/logout");
}

// ---------------------------------------------------------------------------
// Analysis endpoints
// ---------------------------------------------------------------------------

/**
 * Submit Python code for static analysis.
 * @param {string} code - the Python source code
 * @returns {Promise} resolves to { complexity, issues, groq_explanation, ai_status, ... }
 */
export function analyzeCode(code) {
  return api.post("/analyze", { code });
}

// ---------------------------------------------------------------------------
// Scan history endpoints (require login)
// ---------------------------------------------------------------------------

/** List the current user's past scans. */
export function getScans() {
  return api.get("/scans");
}

/** Fetch one scan + its results by id. */
export function getScan(scanId) {
  return api.get(`/scans/${scanId}`);
}

export default api;

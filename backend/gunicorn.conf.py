"""
CodeScan Gunicorn Configuration
================================
Production settings for the WSGI server that runs the Flask app.

Why these settings:
    * bind 127.0.0.1:5000  -> only accessible locally (Nginx proxies to it)
    * workers = 2          -> t2.micro has 1 vCPU & 1GB RAM. The Gunicorn
                              formula is (2*CPU)+1=3, but we cap at 2 to
                              stay within free-tier memory limits.
    * threads = 2          -> handles concurrent requests per worker
                              (important for slow Groq API calls)
    * timeout = 60         -> Groq API can be slow; 60s prevents premature
                              worker kills on the /analyze endpoint
    * accesslog / errorlog -> structured logging for CloudWatch agent

Usage:
    gunicorn --config gunicorn.conf.py "app:create_app()"
"""

import multiprocessing
import os

# Bind to localhost only — Nginx handles external traffic on port 80/443.
bind = "127.0.0.1:5000"

# t2.micro: 1 vCPU, 1GB RAM. 2 workers × 2 threads = 4 concurrent requests.
workers = 2
threads = 2

# Groq can take 5-10 seconds on cold starts. 60s prevents worker restarts.
timeout = 60
graceful_timeout = 30
keepalive = 5

# Logging — CloudWatch agent streams these to CloudWatch Logs.
accesslog = "/var/log/gunicorn/access.log"
errorlog = "/var/log/gunicorn/error.log"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Preload app to share connections and reduce memory per worker.
preload_app = True

# Graceful handling of worker deaths.
max_requests = 1000
max_requests_jitter = 50

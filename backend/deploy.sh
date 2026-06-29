#!/bin/bash
# =============================================================================
# CodeScan Backend Deployment Script
# =============================================================================
# Runs on the EC2 instance to deploy/update the Flask backend.
#
# Usage:
#   cd /home/ubuntu/CodeScan/backend
#   bash deploy.sh
#
# Prerequisites:
#   - .env file exists with production values (DATABASE_URL, GROQ_API_KEY, etc.)
#   - venv created: python3 -m venv venv
# =============================================================================

set -e  # Exit on any error

echo "=========================================="
echo "  CodeScan Backend Deployment"
echo "=========================================="

# Move to backend directory
cd /home/ubuntu/CodeScan/backend

# 1. Pull latest code
echo "[1/6] Pulling latest code from git..."
git pull origin main

# 2. Activate virtual environment
echo "[2/6] Activating virtual environment..."
source venv/bin/activate

# 3. Install/update dependencies
echo "[3/6] Installing dependencies..."
pip install -r requirements.txt --quiet

# 4. Create database tables (uses db.create_all — safe to run repeatedly)
#    NOTE: For schema changes in production, switch to Flask-Migrate + alembic.
echo "[4/6] Ensuring database tables exist..."
python -c "
from app import create_app
from app.models import db
app = create_app()
with app.app_context():
    db.create_all()
    print('Tables created/verified successfully.')
"

# 5. Restart Gunicorn via systemd
echo "[5/6] Restarting Gunicorn service..."
sudo systemctl restart codescan
sleep 2

# 6. Health check
echo "[6/6] Running health check..."
HEALTH=$(curl -s -o /dev/null -w "%{http_code}" http://localhost/health)
if [ "$HEALTH" = "200" ]; then
    echo "✅ Deployment successful! Health check returned 200."
else
    echo "⚠️  Warning: Health check returned $HEALTH. Check logs:"
    echo "   sudo journalctl -u codescan -n 50"
fi

echo "=========================================="
echo "  Backend deployed successfully!"
echo "=========================================="

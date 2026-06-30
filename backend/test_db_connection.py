"""
CodeScan Database Connection Test
=================================
Tests a database connection string to verify it works.
Used to validate your Neon PostgreSQL URL before deploying to EC2.

Usage:
    # Set DATABASE_URL in your .env, then run:
    python test_db_connection.py

    # Or pass the URL directly:
    DATABASE_URL=postgresql://... python test_db_connection.py
"""

import os
import sys
from dotenv import load_dotenv

# Load from .env if present
load_dotenv()

def main():
    print("=" * 60)
    print("CODESCAN DATABASE CONNECTION TEST")
    print("=" * 60)

    db_url = os.environ.get("DATABASE_URL", "").strip()

    if not db_url:
        print("\n❌ FAIL: DATABASE_URL is not set.")
        print("   Either:")
        print("   1. Add it to your .env file: DATABASE_URL=postgresql://...")
        print("   2. Or pass it inline: DATABASE_URL=... python test_db_connection.py")
        return 1

    # Hide the password in the output
    safe_url = db_url.split("@")[0].split(":")[0] + ":****@" + db_url.split("@")[1] if "@" in db_url else db_url
    print(f"\n[1] Testing connection to:")
    print(f"    {safe_url}")

    try:
        from sqlalchemy import create_engine, text
        print("\n[2] Connecting to database...")

        engine = create_engine(db_url)
        with engine.connect() as conn:
            # Test basic query
            result = conn.execute(text("SELECT version()"))
            version = result.fetchone()[0]
            print(f"    ✅ Connected successfully!")
            print(f"    PostgreSQL version: {version[:50]}...")

            # Test table creation capability
            print("\n[3] Testing table creation permissions...")
            conn.execute(text("CREATE TABLE IF NOT EXISTS _codescan_test (id INTEGER)"))
            conn.execute(text("DROP TABLE _codescan_test"))
            conn.commit()
            print("    ✅ Can create tables!")

        print("\n" + "=" * 60)
        print("🎉 SUCCESS! Your database is ready for CodeScan.")
        print("Save this DATABASE_URL — you'll need it on EC2.")
        print("=" * 60)
        return 0

    except Exception as e:
        print(f"\n    ❌ FAIL: Connection failed!")
        print(f"    Error: {e}")
        print("\n" + "=" * 60)
        print("🛑 DIAGNOSIS:")
        if "authentication" in str(e).lower() or "password" in str(e).lower():
            print("   -> Check your username/password in the connection string")
        elif "timeout" in str(e).lower() or "connect" in str(e).lower():
            print("   -> Check if the hostname is correct")
            print("   -> Check your internet connection")
        elif "ssl" in str(e).lower():
            print("   -> Add ?sslmode=require to the end of your URL")
        print("=" * 60)
        return 1

if __name__ == "__main__":
    sys.exit(main())

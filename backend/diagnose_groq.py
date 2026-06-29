"""
CodeScan Groq Diagnostic Script
===============================
Run this to find out exactly WHY the AI feature is failing.
It bypasses Flask and tests the raw Groq connection.

Usage (from backend/ folder):
    python diagnose_groq.py
"""

import os
import sys
from dotenv import load_dotenv

def main():
    print("=" * 60)
    print("CODESCAN GROQ DIAGNOSTIC")
    print("=" * 60)

    # 1. Check if .env exists and loads
    print("\n[1] Checking .env file...")
    if not os.path.exists(".env"):
        print("    ❌ FAIL: No .env file found in the current directory!")
        print("    Fix: Create a file named exactly '.env' in the backend/ folder.")
        return
    load_dotenv()
    print("    ✅ .env loaded successfully.")

    # 2. Check the API key
    print("\n[2] Checking GROQ_API_KEY...")
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        print("    ❌ FAIL: GROQ_API_KEY is empty or missing in .env")
        print("    Fix: Add GROQ_API_KEY=gsk_... to your .env file")
        return
    if "paste" in key or "change" in key:
        print("    ❌ FAIL: You still have the placeholder text in your key!")
        return
    print(f"    ✅ Key found: {key[:8]}...{key[-4:]}")

    # 3. Check Groq SDK
    print("\n[3] Checking Groq SDK...")
    try:
        from groq import Groq
        print("    ✅ Groq SDK installed.")
    except ImportError:
        print("    ❌ FAIL: groq package not installed.")
        print("    Fix: Run 'pip install groq'")
        return

    # 4. Make a live test request
    print("\n[4] Making live test request to Groq API...")
    try:
        client = Groq(api_key=key)
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": "Say 'Hello from Groq!' and nothing else."}],
            max_tokens=20
        )
        reply = response.choices[0].message.content.strip()
        print(f"    ✅ SUCCESS! Groq replied: '{reply}'")
        print("\n" + "=" * 60)
        print("🎉 DIAGNOSIS: Groq is working perfectly!")
        print("If the app still shows 'unavailable', restart your Flask server.")
        print("=" * 60)
    except Exception as e:
        print(f"    ❌ FAIL: API request failed!")
        print(f"    Error Type: {type(e).__name__}")
        print(f"    Error Message: {e}")
        print("\n" + "=" * 60)
        print("🛑 DIAGNOSIS: The Groq API rejected the request.")
        if "401" in str(e) or "Auth" in type(e).__name__:
            print("   -> Your API key is invalid, expired, or copied incorrectly.")
        elif "rate" in str(e).lower():
            print("   -> You hit the free tier rate limit. Wait a minute and retry.")
        print("=" * 60)

if __name__ == "__main__":
    main()

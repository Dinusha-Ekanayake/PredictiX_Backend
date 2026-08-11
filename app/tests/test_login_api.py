#!/usr/bin/env python3
"""Test the login API endpoint directly"""
import os
import sys
import subprocess
import time
import requests
from dotenv import load_dotenv

load_dotenv()

# Check if server is running
api_url = "http://localhost:8000"
print("[*] Checking if API is running on port 8000...")

try:
    response = requests.get(f"{api_url}/", timeout=2)
    print("[+] API is running")
except requests.ConnectionError:
    print("[!] API is NOT running. Starting server...")
    print("\nTo start the server manually, run:")
    print("  uvicorn app.main:app --reload --port 8000")
    sys.exit(1)

# Test login
email = "nuwan.gunasekara.tra1@lankalogix.lk"
password = "user"

print(f"\n[*] Testing login with:")
print(f"    Email: {email}")
print(f"    Password: {password}")

try:
    response = requests.post(
        f"{api_url}/auth/login",
        json={"email": email, "password": password},
        timeout=5
    )

    print(f"\n[*] Response Status: {response.status_code}")

    if response.status_code == 200:
        print("[+] LOGIN SUCCESSFUL!")
        data = response.json()
        print(f"    Access Token: {data.get('access_token', '(none)')[:50]}...")
        print(f"    User ID: {data.get('user_id')}")
        print(f"    Role: {data.get('role')}")
        print(f"    Full Name: {data.get('full_name')}")
    else:
        print("[X] LOGIN FAILED!")
        print(f"    Error: {response.text}")

except Exception as e:
    print(f"[X] Request failed: {e}")

print("\n" + "="*60)
print("If login failed, check:")
print("  1. Is the API server running? (uvicorn app.main:app --reload --port 8000)")
print("  2. Are JWT credentials correct in .env?")
print("  3. Check application logs for detailed error messages")

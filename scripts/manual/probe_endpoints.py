import requests
import json
import sys

BASE_URL = "http://127.0.0.1:8000"
CREDENTIALS = {
    "email": "anjali.warnakulasuriya.adm1@lankalogix.lk",
    "password": "admin",
    "role": "admin"
}

results = {
    "passed": [],
    "failed": []
}

def log_pass(name):
    print(f"PASS: {name}")
    results["passed"].append(name)

def log_fail(name, reason=""):
    print(f"FAIL: {name} - {reason}")
    results["failed"].append({"name": name, "reason": reason})

def run_tests():
    try:
        # 1. Auth
        print("Testing Authentication...")
        r = requests.post(f"{BASE_URL}/auth/login", json=CREDENTIALS)
        if r.status_code == 200:
            token = r.json().get("access_token")
            log_pass("Auth Login")
        else:
            log_fail("Auth Login", f"Status {r.status_code}: {r.text}")
            return
            
        headers = {"Authorization": f"Bearer {token}"}
        
        # 2. Profiles
        print("Testing Profiles...")
        r = requests.get(f"{BASE_URL}/profiles/me", headers=headers)
        if r.status_code == 200:
            log_pass("Get Current Profile")
        else:
            log_fail("Get Current Profile", f"Status {r.status_code}")

        # 3. Warehouses & Departments
        print("Testing Warehouses & Departments...")
        r = requests.get(f"{BASE_URL}/warehouses", headers=headers)
        if r.status_code == 200:
            log_pass("List Warehouses")
        else:
            log_fail("List Warehouses", f"Status {r.status_code}")
            
        r = requests.get(f"{BASE_URL}/departments", headers=headers)
        if r.status_code == 200:
            log_pass("List Departments")
        else:
            log_fail("List Departments", f"Status {r.status_code}")

        # 4. Assets
        print("Testing Assets...")
        r = requests.get(f"{BASE_URL}/assets?limit=5", headers=headers)
        asset_id = None
        if r.status_code == 200:
            log_pass("List Assets")
            assets = r.json()
            if assets and len(assets) > 0:
                asset_id = assets[0].get("id")
        else:
            log_fail("List Assets", f"Status {r.status_code}: {r.text}")
            
        if asset_id:
            r = requests.get(f"{BASE_URL}/assets/{asset_id}", headers=headers)
            if r.status_code == 200:
                log_pass("Get Single Asset")
            else:
                log_fail("Get Single Asset", f"Status {r.status_code}")

            # 5. Predictions
            print("Testing Predictions (Health & Specific Asset)...")
            r = requests.get(f"{BASE_URL}/predictions/health", headers=headers)
            if r.status_code == 200:
                log_pass("Predictions API Health")
            else:
                log_fail("Predictions API Health", f"Status {r.status_code}")

            r = requests.get(f"{BASE_URL}/predictions/failure/{asset_id}", headers=headers)
            if r.status_code in [200, 404]: # 404 just means no run exists, which is fine structurally
                log_pass("Get Asset Failure Prediction")
            else:
                log_fail("Get Asset Failure Prediction", f"Status {r.status_code}: {r.text}")

        # 6. Tickets
        print("Testing Tickets...")
        r = requests.get(f"{BASE_URL}/tickets?limit=5", headers=headers)
        if r.status_code == 200:
            log_pass("List Tickets")
        else:
            log_fail("List Tickets", f"Status {r.status_code}")

        # 7. Dashboard / Summary
        print("Testing Dashboard Summaries...")
        r = requests.get(f"{BASE_URL}/warehouse-dashboard/summary", headers=headers)
        if r.status_code == 200:
            log_pass("Warehouse Dashboard Summary")
        else:
            log_fail("Warehouse Dashboard Summary", f"Status {r.status_code}: {r.text}")

    except Exception as e:
        log_fail("Test Execution Exception", str(e))
        
    print("\n--- Test Summary ---")
    print(f"Passed: {len(results['passed'])}")
    print(f"Failed: {len(results['failed'])}")
    
    with open("test_results.json", "w") as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    run_tests()

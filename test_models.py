import requests
import sys
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Configure retry logic for all requests
retry_strategy = Retry(
    total=5,
    backoff_factor=2,
    status_forcelist=[500, 502, 503, 504],
    allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
)
adapter = HTTPAdapter(max_retries=retry_strategy)
http = requests.Session()
http.mount("http://", adapter)
http.mount("https://", adapter)

# Wait for server to start initially
print("Waiting for server to start...")
time.sleep(10)

BASE_URL = "http://127.0.0.1:8000"

def test_endpoint(name, method, path, json=None):
    url = f"{BASE_URL}{path}"
    print(f"\n--- Testing {name} ---")
    try:
        if method == "POST":
            res = http.post(url, json=json, timeout=30)
        else:
            res = http.get(url, timeout=30)
        
        print(f"Status: {res.status_code}")
        if res.status_code == 200:
            print("Response:", res.json())
            return res.json()
        else:
            print("Error Response:", res.text)
            return None
    except Exception as e:
        print(f"Failed to connect or timeout: {e}")
        return None

def main():
    # 1. Ticket Categorization
    test_endpoint(
        "Ticket Categorization Model", 
        "POST", "/tickets/categorize", 
        {"title": "Forklift engine won't start", "description": "The engine makes a clicking noise but doesn't turn over."}
    )

    # 2. Ticket Priority Classification
    test_endpoint(
        "Ticket Priority Model", 
        "POST", "/tickets/prioritize", 
        {"text": "Forklift engine won't start The engine makes a clicking noise but doesn't turn over."}
    )

    # 3. Ticket Summary
    test_endpoint(
        "Ticket Summary Model", 
        "POST", "/tickets/summarize", 
        {"title": "Forklift engine won't start", "description": "The engine makes a clicking noise but doesn't turn over.", "asset_name": "Forklift A"}
    )

    # 4. Asset Summary
    test_endpoint(
        "Asset Summary Model", 
        "POST", "/asset-summaries/generate", 
        {"input_text": "Asset: Forklift A, Status: Broken down, Priority: High. Needs immediate engine repair."}
    )

    # Find an asset for PdM
    assets_res = test_endpoint("Get Assets (for PdM testing)", "GET", "/assets/?limit=1")
    if not assets_res or not isinstance(assets_res, list) or len(assets_res) == 0:
        print("No assets found. Cannot test PdM and Cost models.")
        sys.exit(1)
        
    asset_id = assets_res[0].get("id")
    print(f"Found Asset ID: {asset_id}")

    # 5. Vehicle Prediction (PdM Classifier, Regressor, Cost Estimation)
    test_endpoint(
        "Vehicle Prediction (PdM Classifier, Regressor, Cost)", 
        "POST", f"/vehicle-predictions/{asset_id}", 
        {}
    )

if __name__ == "__main__":
    main()

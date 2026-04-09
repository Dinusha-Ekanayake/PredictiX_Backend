#!/usr/bin/env python3
"""
Test script for User Role implementation
Run this to verify the authentication and user endpoints work correctly
"""

import requests
import json

BASE_URL = "http://localhost:8000"

# ANSI color codes for output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"


def print_test(name):
    print(f"\n{BOLD}▶ {name}{RESET}")


def print_success(message):
    print(f"{GREEN}✓ {message}{RESET}")


def print_error(message):
    print(f"{RED}✗ {message}{RESET}")


def print_info(message):
    print(f"{YELLOW}ℹ {message}{RESET}")


def test_login():
    """Test login endpoint"""
    print_test("Testing Login Endpoint")
    
    # Note: Update these credentials with actual test user from database
    payload = {
        "email": "sharada.fernando@lankalogix.com",  # From seed data
        "password": "test_password"  # Mock password for now
    }
    
    try:
        response = requests.post(f"{BASE_URL}/auth/login", json=payload)
        
        if response.status_code == 200:
            data = response.json()
            print_success(f"Login successful")
            print_info(f"Token: {data['access_token'][:50]}...")
            print_info(f"User: {data['user']['full_name']} ({data['user']['role']})")
            return data['access_token']
        else:
            print_error(f"Login failed: {response.status_code}")
            print_info(f"Response: {response.text}")
            return None
    except Exception as e:
        print_error(f"Login request failed: {str(e)}")
        return None


def test_protected_endpoints(token):
    """Test protected endpoints"""
    
    if not token:
        print_error("No token available, skipping protected endpoint tests")
        return
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # Test 1: Get current user profile
    print_test("GET /profiles/me (Current User Profile)")
    try:
        response = requests.get(f"{BASE_URL}/profiles/me", headers=headers)
        if response.status_code == 200:
            user = response.json()
            print_success(f"Got profile: {user['full_name']}")
            print_info(f"Role: {user['role']}, Status: {user['status']}")
        else:
            print_error(f"Failed: {response.status_code}")
    except Exception as e:
        print_error(f"Request failed: {str(e)}")
    
    # Test 2: Get user's tickets
    print_test("GET /tickets/my (My Tickets)")
    try:
        response = requests.get(f"{BASE_URL}/tickets/my", headers=headers)
        if response.status_code == 200:
            tickets = response.json()
            print_success(f"Got {len(tickets)} tickets")
            for ticket in tickets[:3]:  # Show first 3
                print_info(f"  - {ticket.get('title', 'N/A')} ({ticket.get('status', 'N/A')})")
        else:
            print_error(f"Failed: {response.status_code}")
    except Exception as e:
        print_error(f"Request failed: {str(e)}")
    
    # Test 3: Get user's notifications
    print_test("GET /user-notifications (My Notifications)")
    try:
        response = requests.get(f"{BASE_URL}/user-notifications", headers=headers)
        if response.status_code == 200:
            notifications = response.json()
            print_success(f"Got {len(notifications)} notifications")
            for notif in notifications[:3]:
                print_info(f"  - {notif.get('title', 'N/A')} ({notif.get('status', 'N/A')})")
        else:
            print_error(f"Failed: {response.status_code}")
    except Exception as e:
        print_error(f"Request failed: {str(e)}")
    
    # Test 4: Get unread notifications
    print_test("GET /user-notifications/unread")
    try:
        response = requests.get(f"{BASE_URL}/user-notifications/unread", headers=headers)
        if response.status_code == 200:
            unread = response.json()
            print_success(f"Got {len(unread)} unread notifications")
        else:
            print_error(f"Failed: {response.status_code}")
    except Exception as e:
        print_error(f"Request failed: {str(e)}")
    
    # Test 5: Get tickets with filters
    print_test("GET /tickets?status=open (Filtered Tickets)")
    try:
        response = requests.get(f"{BASE_URL}/tickets?status=open", headers=headers)
        if response.status_code == 200:
            tickets = response.json()
            print_success(f"Got {len(tickets)} open tickets")
        else:
            print_error(f"Failed: {response.status_code}")
    except Exception as e:
        print_error(f"Request failed: {str(e)}")


def test_unauthorized():
    """Test unauthorized access"""
    print_test("Testing Unauthorized Access")
    
    # Try without token
    try:
        response = requests.get(f"{BASE_URL}/profiles/me")
        if response.status_code == 403:
            print_success("Correctly rejected request without token (403)")
        else:
            print_info(f"Response: {response.status_code} (expected 403)")
    except Exception as e:
        print_error(f"Request failed: {str(e)}")
    
    # Try with invalid token
    try:
        headers = {"Authorization": "Bearer invalid_token_xyz"}
        response = requests.get(f"{BASE_URL}/profiles/me", headers=headers)
        if response.status_code == 401:
            print_success("Correctly rejected invalid token (401)")
        else:
            print_info(f"Response: {response.status_code} (expected 401)")
    except Exception as e:
        print_error(f"Request failed: {str(e)}")


def test_public_endpoints():
    """Test public endpoints (no auth required)"""
    print_test("Testing Public Endpoints (No Auth Required)")
    
    # Test 1: List all profiles
    print_test("GET /profiles (List All Profiles)")
    try:
        response = requests.get(f"{BASE_URL}/profiles")
        if response.status_code == 200:
            profiles = response.json()
            print_success(f"Got {len(profiles)} profiles")
        else:
            print_error(f"Failed: {response.status_code}")
    except Exception as e:
        print_error(f"Request failed: {str(e)}")
    
    # Test 2: List all tickets
    print_test("GET /tickets (List All Tickets)")
    try:
        response = requests.get(f"{BASE_URL}/tickets")
        if response.status_code == 200:
            tickets = response.json()
            print_success(f"Got {len(tickets)} tickets")
        else:
            print_error(f"Failed: {response.status_code}")
    except Exception as e:
        print_error(f"Request failed: {str(e)}")


def main():
    print(f"\n{BOLD}{'='*60}")
    print(f"PredictiX User Role Implementation - Test Suite")
    print(f"{'='*60}{RESET}")
    
    print(f"\n{BOLD}Base URL: {BASE_URL}{RESET}")
    
    # Run tests
    test_public_endpoints()
    test_unauthorized()
    
    token = test_login()
    
    test_protected_endpoints(token)
    
    print(f"\n{BOLD}{'='*60}")
    print(f"Tests Complete!")
    print(f"{'='*60}{RESET}\n")


if __name__ == "__main__":
    main()

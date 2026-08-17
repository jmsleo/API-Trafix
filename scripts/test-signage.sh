#!/bin/bash
# Test script for BSS Parking Signage System

API_BASE="http://localhost:8000"

echo "=== BSS Parking Signage System Test ==="
echo ""

# Test 1: Check API health
echo "1. Checking API health..."
curl -s "$API_BASE/health" | python3 -m json.tool
echo ""

# Test 2: Check signage status
echo "2. Checking signage status for gate 1..."
curl -s "$API_BASE/api/signage/status/1" | python3 -m json.tool
echo ""

# Test 3: Update signage status to welcome
echo "3. Setting signage status to 'welcome'..."
curl -s -X POST "$API_BASE/api/signage/status/1" \
    -H "Content-Type: application/json" \
    -d '{"status": "welcome", "plate_number": "B 1234 XYZ"}' | python3 -m json.tool
echo ""

# Test 4: Check signage status again
echo "4. Checking signage status after update..."
curl -s "$API_BASE/api/signage/status/1" | python3 -m json.tool
echo ""

# Test 5: Simulate vehicle detected (GPIO bridge callback)
echo "5. Simulating vehicle detected..."
curl -s -X POST "$API_BASE/api/signage/vehicle-detected" \
    -H "Content-Type: application/json" \
    -d '{"gate": "1"}' | python3 -m json.tool
echo ""

# Test 6: Simulate help button press
echo "6. Simulating help button press..."
curl -s -X POST "$API_BASE/api/signage/help-button" \
    -H "Content-Type: application/json" \
    -d '{"gate": "1"}' | python3 -m json.tool
echo ""

# Test 7: Update signage status to thanks
echo "7. Setting signage status to 'thanks'..."
curl -s -X POST "$API_BASE/api/signage/status/1" \
    -H "Content-Type: application/json" \
    -d '{"status": "thanks", "plate_number": "B 1234 XYZ", "transaction_code": "TRX001"}' | python3 -m json.tool
echo ""

# Test 8: Check SSE stream (timeout after 5 seconds)
echo "8. Testing SSE stream (5 second timeout)..."
timeout 5 curl -s -N "$API_BASE/api/signage/stream/1" || true
echo ""

echo "=== Test Complete ==="
echo ""
echo "To view the signage display, open in browser:"
echo "  $API_BASE/signage/?gate=1"

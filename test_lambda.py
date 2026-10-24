import os
import requests
import json

# Local or production URL of your Flask app
API_URL = "http://127.0.0.1:8000/api/automation/event"  # Update to match your actual route
API_KEY = "change-this-automations-key"               # Matches your AUTOMATION_API_KEY in config

def lambda_handler(event, context):
    """
    Simulates the AWS Lambda handler function processing an IoT / weather event
    and notifying the Flask backend.
    """
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": API_KEY
    }
    
    payload = {
        "device_id": event.get("device_id", "esp32_iot_sensor_01"),
        "zone_id": event.get("zone_id", 1),
        "moisture_level": event.get("moisture_level", 12.5),
        "status": "CRITICAL_DROUGHT_RISK"
    }
    
    print(f"Sending payload from simulated Lambda to Flask: {payload}")
    
    try:
        response = requests.post(API_URL, headers=headers, json=payload)
        print(f"Response status: {response.status_code}")
        print(f"Response body: {response.text}")
        return {"statusCode": response.status_code, "body": response.text}
    except Exception as e:
        print(f"Failed to reach Flask backend: {e}")
        return {"statusCode": 500, "body": str(e)}

if __name__ == "__main__":
    # Test event payload simulating an IoT sensor trigger
    sample_event = {
        "device_id": "esp32_field_sensor_99",
        "zone_id": 2,
        "moisture_level": 9.4
    }
    lambda_handler(sample_event, None)
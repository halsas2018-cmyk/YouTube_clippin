#!/usr/bin/env python3
import os
import requests
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(env_path, override=False)

pixabay_key = os.environ.get("PIXABAY_API_KEY", "").strip()
if not pixabay_key:
    print("PIXABAY_API_KEY not found in .env")
    exit(1)

print(f"Using PIXABAY_API_KEY: {pixabay_key[:10]}...")

# Test the Pixabay audio API with parameters similar to video
url = "https://pixabay.com/api/audio/"
params = {
    'key': pixabay_key,
    'q': 'whoosh',
    'per_page': 3,
}
try:
    response = requests.get(url, params=params, timeout=10)
    print(f"Status code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Total hits: {data.get('totalHits', 0)}")
        if data['hits']:
            hit = data['hits'][0]
            print(f"First hit: {hit.get('id')} - {hit.get('tags')}")
            print(f"Preview URL: {hit.get('previewURL')}")
            # Check if there is a 'url' field for direct download?
            print(f"Fields: {list(hit.keys())}")
        else:
            print("No hits found")
            print(f"Full response: {data}")
    else:
        print(f"Response text: {response.text}")
except Exception as e:
    print(f"Error: {e}")
import os
import requests
import json
from api_limiter import APILimiter

config_path = os.path.join(os.path.dirname(__file__), 'config.json')
with open(config_path) as f:
    CONFIG = json.load(f)

API_KEY = CONFIG["torn_api_key"]

limiter = APILimiter()

def safe_get(url):
    if limiter.allow():
        r = requests.get(url)
        return r.json()
    else:
        print("⚠️ API Rate Limit Hit: Skipping call")
        return {}

def get_faction_data():
    url = f"https://api.torn.com/faction/?selections=basic,crimes,members&key={API_KEY}"
    return safe_get(url)

def get_member_status(user_id):
    url = f"https://api.torn.com/user/{user_id}?selections=profile,crimes&key={API_KEY}"
    return safe_get(url)

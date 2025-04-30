import gspread
from google.oauth2.service_account import Credentials
import json

def load_cpr_data():
    with open("config.json") as f:
        config = json.load(f)

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_file("google_creds.json", scopes=scopes)
    client = gspread.authorize(creds)

    sheet = client.open_by_key(config['google_sheet_id']).worksheet(config['cpr_sheet_name'])
    data = sheet.get_all_records()

    cpr_map = {}
    for row in data:
        pid = str(row.get("Player ID")).strip()
        cpr_map[pid] = row
    return cpr_map

import os
import base64
import json

print("=== DEBUG START ===")

# Grab environment variables
creds_b64 = os.getenv("GOOGLE_CREDENTIALS_B64")
sheet_id = os.getenv("SHEET_ID")
telegram_token = os.getenv("TELEGRAM_TOKEN")
telegram_id = os.getenv("TELEGRAM_ID")

print("GOOGLE_CREDENTIALS_B64 present?:", creds_b64 is not None)
if creds_b64:
    print("First 50 chars of GOOGLE_CREDENTIALS_B64:", creds_b64[:50])

print("SHEET_ID:", sheet_id)
print("TELEGRAM_TOKEN present?:", telegram_token is not None)
print("TELEGRAM_ID:", telegram_id)

try:
    if creds_b64:
        creds_json = base64.b64decode(creds_b64).decode("utf-8")
        creds_dict = json.loads(creds_json)
        print("Decoded JSON keys:", list(creds_dict.keys()))
    else:
        print("⚠️ GOOGLE_CREDENTIALS_B64 is None")
except Exception as e:
    print("Error decoding GOOGLE_CREDENTIALS_B64:", e)

print("=== DEBUG END ===")

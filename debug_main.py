import os, base64, json, sys

print("=== DEBUG START ===")

# Print all env keys we can see
print("Environment keys available:", list(os.environ.keys()))

# Try to read GOOGLE_CREDENTIALS_B64
creds_b64 = os.environ.get("GOOGLE_CREDENTIALS_B64")
if creds_b64 is None:
    print("ERROR: GOOGLE_CREDENTIALS_B64 is missing or not set!")
    sys.exit(1)

print("GOOGLE_CREDENTIALS_B64 length:", len(creds_b64))

try:
    creds_json = base64.b64decode(creds_b64).decode("utf-8")
    print("Decoded credentials JSON length:", len(creds_json))
    creds_dict = json.loads(creds_json)
    print("Decoded credentials keys:", list(creds_dict.keys()))
except Exception as e:
    print("ERROR decoding GOOGLE_CREDENTIALS_B64:", str(e))
    sys.exit(1)

# Check other env variables
sheet_id = os.environ.get("SHEET_ID")
telegram_token = os.environ.get("TELEGRAM_TOKEN")
telegram_id = os.environ.get("TELEGRAM_ID")

print("SHEET_ID:", sheet_id)
print("TELEGRAM_TOKEN:", telegram_token[:8] + "..." if telegram_token else None)
print("TELEGRAM_ID:", telegram_id)

print("=== DEBUG END ===")

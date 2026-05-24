import json, os, secrets, hashlib, hmac
from datetime import datetime

auth_path = "/config/.storage/auth"
with open(auth_path) as f:
    auth = json.load(f)

# Find the first user (owner)
users = auth["data"].get("users", [])
owner = None
for u in users:
    if u.get("is_owner"):
        owner = u
        break
if not owner:
    owner = users[0] if users else None

if not owner:
    print("No user found")
    exit(1)

# Generate a new long-lived access token
import uuid
token_id = str(uuid.uuid4())
raw_token = secrets.token_hex(64)

refresh_token = {
    "id": token_id,
    "user_id": owner["id"],
    "client_id": None,
    "client_name": "Kyber Dev",
    "client_icon": None,
    "token_type": "long_lived_access_token",
    "created_at": datetime.now().isoformat(),
    "access_token_expiration": 315360000.0,
    "token": hashlib.sha512(raw_token.encode()).hexdigest(),
    "jwt_key": secrets.token_hex(32),
    "last_used_at": None,
    "last_used_ip": None,
    "credential_id": None,
    "version": "2025.4.4"
}

auth["data"]["refresh_tokens"].append(refresh_token)

with open(auth_path, "w") as f:
    json.dump(auth, f, indent=2)

print(f"Token ID: {token_id}")
print(f"User: {owner.get('name', owner['id'])}")
print("Token created - restart HA to activate")
print(f"NOTE: You need the JWT, not the raw token. Restart HA first.")

import json
with open("/config/.storage/auth") as f:
    auth = json.load(f)
for token in auth.get("data", {}).get("refresh_tokens", []):
    if token.get("token_type") == "long_lived_access_token":
        print(f"Token ID: {token['id']}")
        print(f"Name: {token.get('client_name', 'unknown')}")
        # Can't extract the actual token from storage, just verify it exists
        break
else:
    print("No long-lived access token found")

# Check if there's a token we can use
for token in auth.get("data", {}).get("refresh_tokens", []):
    print(f"  Type: {token.get('token_type')}, Client: {token.get('client_name', token.get('client_id', 'n/a'))}")

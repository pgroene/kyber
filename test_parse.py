import json, urllib.request

yaml_body = "alias: Test\ntrigger:\n  - trigger: state\n    entity_id: sun.sun\nmetadata:\n{}\ncondition: []\naction:\n  - action: light.turn_on\n    target:\n      entity_id: light.kitchen\n    data:\n{}"

token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiI2MzE3Y2RkYzA4OWY0MTI5OWQ2MmI3MjJmYjVkNGZhMyIsImlhdCI6MTczOTcyMTc5NCwiZXhwIjoyMDU1MDgxNzk0fQ.NdsKnUbpfT9vemhxABI8t8xYFrgJiDhr_TeYH35brYs"

req = urllib.request.Request(
    "http://localhost:8123/api/kyber/parse_yaml",
    data=json.dumps({"yaml": yaml_body}).encode(),
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    method="POST"
)
try:
    resp = urllib.request.urlopen(req)
    body = json.loads(resp.read())
    print("Status:", resp.status)
    print("Triggers:", len(body.get("config", {}).get("trigger", [])))
    print("OK")
except urllib.error.HTTPError as e:
    print("Error:", e.code, e.read().decode())

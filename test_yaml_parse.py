import yaml, re

yaml_text = "alias: Test\ntrigger:\n  - trigger: state\n    entity_id: sun.sun\n  - trigger: sun\n    event: sunrise\nmetadata:\n{}\ncondition: []\naction:\n  - action: light.turn_on\n    target:\n      entity_id: light.kitchen\n    data:\n{}\n"

cleaned = re.sub(r"^\s*(\{\}|\[\])\s*$", "", yaml_text, flags=re.MULTILINE)
result = yaml.safe_load(cleaned)
print("Triggers:", len(result.get("trigger", [])))
print("Actions:", len(result.get("action", [])))
print("Condition:", result.get("condition"))

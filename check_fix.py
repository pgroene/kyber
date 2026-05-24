import re
text = open("/config/custom_components/kyber/api_utilities.py").read()
for i, line in enumerate(text.split("\n")):
    if "re.sub" in line:
        print(f"Line {i+1}: {line.strip()}")

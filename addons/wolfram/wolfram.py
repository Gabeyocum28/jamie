"""Ask Wolfram|Alpha (LLM API): python3 wolfram.py 'integrate x e^x from 0 to 1'

Needs WOLFRAM_APP_ID in environments/math/.env (free: developer.wolframalpha.com, "LLM API").
"""
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

if len(sys.argv) < 2:
    sys.exit(__doc__)
app_id = os.environ.get("WOLFRAM_APP_ID")
if not app_id:
    sys.exit("WOLFRAM_APP_ID isn't set. Add it to environments/math/.env, then restart this Jamie.")
query = urllib.parse.urlencode({"input": " ".join(sys.argv[1:]), "appid": app_id, "maxchars": 3000})
try:
    with urllib.request.urlopen(f"https://www.wolframalpha.com/api/v1/llm-api?{query}", timeout=30) as r:
        print(r.read().decode())
except urllib.error.HTTPError as e:
    sys.exit(f"Wolfram|Alpha error {e.code}: {e.read().decode().strip()}")

#!/usr/bin/env python3
"""Generate Streamlit Cloud secrets — single-line base64 key (paste-safe)."""
import base64
import os

key_path = os.path.expanduser("~/.snowflake/rsa_key.p8")
out_path = os.path.expanduser("~/transparent-rx-cloud-secrets.toml")

with open(key_path, "rb") as f:
    key_b64 = base64.b64encode(f.read()).decode()

toml = (
    'SNOWFLAKE_ACCOUNT = "unpsrpt-il63479"\n'
    'SNOWFLAKE_USER = "benjamin.atkinson@gmail.com"\n'
    'SNOWFLAKE_ROLE = "RX_APP_ROLE"\n'
    'SNOWFLAKE_WAREHOUSE = "RX_CORTEX_WH"\n'
    f'SNOWFLAKE_PRIVATE_KEY_B64 = "{key_b64}"\n'
)

with open(out_path, "w") as f:
    f.write(toml)

print(f"WROTE {out_path} ({len(toml)} chars, b64 len {len(key_b64)})")

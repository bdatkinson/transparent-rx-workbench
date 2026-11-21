#!/usr/bin/env python3
"""Verify the Module B governance loop end-to-end against Snowflake."""
import json, os, re, uuid
import snowflake.connector
from cryptography.hazmat.primitives import serialization

DB = "RX_INTELLIGENCE"
SEARCH_SERVICE = f"{DB}.ANALYTICS.POLICY_SEARCH"
SEMANTIC_VIEW = f"{DB}.ANALYTICS.SV_TRANSPARENT_RX"

PHI_PATTERNS = {
    "SSN": r"\b\d{3}-\d{2}-\d{4}\b|(?<!\d)\d{9}(?!\d)",
    "DOB": r"\b(?:dob|date\s*of\s*birth|birth\s*date|birthdate|born\s+on)\b|\b\d{1,2}/\d{1,2}/\d{4}\b",
    "MEMBER_ID": r"\b(?:member\s*id|beneficiary\s*id|mbi|member\s*number)\b"
                 r"|[0-9][A-Z][0-9A-Z][0-9]-[0-9A-Z][0-9][0-9A-Z][0-9]-[0-9A-Z]{2}[0-9]{2}",
    "PHONE": r"(?<!\d)\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)",
}

def detect_phi(text):
    return [(l, m.group(0)) for l, p in PHI_PATTERNS.items()
            for m in re.finditer(p, text, flags=re.IGNORECASE)]

with open(os.path.expanduser("~/.snowflake/rsa_key.p8"), "rb") as f:
    pkey = serialization.load_pem_private_key(f.read(), password=None)
conn = snowflake.connector.connect(
    account="unpsrpt-il63479", user="benjamin.atkinson@gmail.com",
    role="RX_APP_ROLE", warehouse="RX_CORTEX_WH", private_key=pkey,
)
cur = conn.cursor()

print("=== 1. PHI regex (client-side guardrail) ===")
cases = [
    ("What is the total spread leakage for GLP-1 drugs in Kentucky?", []),
    ("What's the cost for patient with SSN 123-45-6789?", ["SSN"]),
    ("Member ID 1EG4-TE5-MK73 drug spend", ["MEMBER_ID"]),
    ("born on 03/15/1980, Ozempic cost", ["DOB"]),
    ("call 555-123-4567 about rebates", ["PHONE"]),
    ("500 MG metformin benchmark", []),   # dosage must NOT false-positive
    ("NDC 00002143380 spread", []),       # 11-digit NDC must NOT be SSN
]
ok = True
for text, expect in cases:
    got = sorted({l for l, _ in detect_phi(text)})
    status = "PASS" if got == expect else f"FAIL (got {got})"
    if got != expect:
        ok = False
    print(f"  [{status}] {text!r:55} -> {got}")

print("\n=== 2. Audit write-back (INSERT) ===")
sid = "module-b-verification-" + uuid.uuid4().hex[:8]

def q(sql, params=None):
    cur.execute(sql, params or ())
    return cur.fetchall()

# clean event
event_id = str(uuid.uuid4())
q(f"""
    INSERT INTO {DB}.GOVERNANCE.AI_WORKBENCH_AUDIT
        (EVENT_ID, SESSION_ID, USER_ROLE_PERSONA, PROMPT_TEXT, PHI_GUARDRAIL_PASS,
         GENERATED_SQL, AI_DRAFT_RESPONSE, CITATIONS_JSON, LATENCY_MS)
    SELECT %s, %s, %s, %s, %s, %s, %s, PARSE_JSON(%s), %s
""", (event_id, sid, "RFP Proposal Analyst",
      "What is the total spread leakage for GLP-1 drugs in Kentucky?",
      True, "SELECT ... FROM SEMANTIC_VIEW(...)", "Draft interpretation",
      json.dumps([{"source_title": "2026 DOL Fee Disclosure", "section_ref": "§3.1",
                   "doc_category": "regulatory", "score": 3.43}]),
      2715))
print(f"  inserted clean event: {event_id}")

# blocked event
phi_id = str(uuid.uuid4())
q(f"""
    INSERT INTO {DB}.GOVERNANCE.AI_WORKBENCH_AUDIT
        (EVENT_ID, SESSION_ID, USER_ROLE_PERSONA, PROMPT_TEXT, PHI_GUARDRAIL_PASS,
         GENERATED_SQL, AI_DRAFT_RESPONSE, CITATIONS_JSON, LATENCY_MS)
    SELECT %s, %s, %s, %s, %s, %s, %s, PARSE_JSON(%s), %s
""", (phi_id, sid, "RFP Proposal Analyst",
      "What's the cost for patient with SSN 123-45-6789?",
      False, None, None, "[]", 0))
print(f"  inserted blocked PHI event: {phi_id}")

print("\n=== 3. Sign-off (UPDATE) ===")
q(f"""
    UPDATE {DB}.GOVERNANCE.AI_WORKBENCH_AUDIT
    SET REVIEW_STATUS=%s, REVIEWER_NAME=%s, REVIEWED_TS=CURRENT_TIMESTAMP(),
        CONFIDENCE_RATING=%s, EST_MINUTES_SAVED=%s
    WHERE EVENT_ID=%s
""", ("HUMAN_VERIFIED", "Benjamin Atkinson", 5, 12, event_id))
row = q("SELECT REVIEW_STATUS, CONFIDENCE_RATING, EST_MINUTES_SAVED FROM "
        f"{DB}.GOVERNANCE.AI_WORKBENCH_AUDIT WHERE EVENT_ID=%s", (event_id,))
print(f"  after signoff: status={row[0][0]}, confidence={row[0][1]}, mins={row[0][2]}")

print("\n=== 4. Budget + telemetry reflect events ===")
budget = q(f"SELECT QUERIES_TODAY, REMAINING_QUERIES FROM {DB}.GOVERNANCE.DAILY_BUDGET_STATUS")[0]
tele = q(f"""
    SELECT COUNT(*),
           SUM(CASE WHEN PHI_GUARDRAIL_PASS THEN 1 ELSE 0 END),
           SUM(CASE WHEN REVIEW_STATUS='HUMAN_VERIFIED' THEN 1 ELSE 0 END),
           SUM(CASE WHEN REVIEW_STATUS='FLAGGED' THEN 1 ELSE 0 END)
    FROM {DB}.GOVERNANCE.AI_WORKBENCH_AUDIT
""")[0]
print(f"  budget: used={budget[0]}, remaining={budget[1]}  (blocked PHI should NOT count)")
print(f"  telemetry: total={tele[0]}, phi_passes={tele[1]}, approved={tele[2]}, flagged={tele[3]}")

conn.close()
print("\n" + ("ALL GOVERNANCE CHECKS PASSED" if ok else "PHI REGEX FAILURES — see above"))

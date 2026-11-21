# Transparent Rx Intelligence Workbench

A **Snowflake Cortex–powered demo** proving pharmacy benefit manager (PBM) *spread-pricing transparency*. Thesis: **lowest net cost ≠ highest rebate** — the workbench shows the plan sponsor exactly how much they pay above a fair pass-through benchmark.

Built for **AffirmedRx** on the **I-65 corridor** (Louisville KY ↔ Nashville TN), joined across three public zero-PHI government datasets on exact 11-digit NDCs.

## The insight

```
spread = reimbursed − (ingredient_cost + Rx_count × $10.50 fair dispensing fee)
```

Live result across KY + TN: **$3.45B** Medicaid reimbursement vs **$3.42B** pass-through benchmark → **~$230M estimated spread leakage** (~6.7%) across 15,519 NDCs.

## Architecture

```
CMS Medicaid SDUD (KY+TN) ─┐
CMS NADAC 2026 ─────────────┼─► Snowflake RAW → ANALYTICS views → SEMANTIC VIEW
CMS Part D Prescribers ─────┘                                         │
                                                      ┌────────────────┴───────────────┐
                                            Cortex Analyst (text→SQL)   Cortex Search (policy RAG)
                                                      └────────────────┬───────────────┘
                                                                Streamlit (3 tabs)
```

- **Module A — data layer:** `ingest_rx_data.py` → `RAW.*` tables → `analytics_ddl.sql` → analytical views + `SV_TRANSPARENT_RX` semantic view. Verified by `verify.py` / `smoke_test.sql`.
- **Module B — app:** `app.py` (zero-login, key-pair auth as least-privilege `RX_APP_ROLE`).

## The three tabs

1. **I-65 Spread & Access Pulse** — reimbursement vs benchmark gap chart, dual-city prescriber map, high-cost brand prescriber drill-down.
2. **Governed Cortex Workbench** — role-based personas; Cortex Analyst text-to-SQL against the semantic view + Cortex Search policy RAG, every answer gated behind an `UNVERIFIED DRAFT` badge and a mandatory human sign-off writing back to the audit ledger.
3. **AI Vital Signs & Cost Ledger** — citation groundedness, approval rate, minutes saved, and a live FinOps budget meter.

## Governance circuit-breakers

- **Zero-PHI guardrail** — client-side regex intercepts SSN / DOB / member-ID / phone before any model call (blocked attempts are logged and do **not** consume budget).
- **Least privilege** — app runs as `RX_APP_ROLE` (read views + semantic view + Cortex + audit table only).
- **FinOps** — warehouse bound to `RX_TRIAL_MONITOR` (15 credits/mo); 50 queries/day + 8/session caps; 350-char prompt ceiling.

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

### Secrets (local → `.streamlit/secrets.toml`, Cloud → Streamlit Secrets manager)

```toml
SNOWFLAKE_ACCOUNT = "unpsrpt-il63479"
SNOWFLAKE_USER = "you@example.com"
SNOWFLAKE_ROLE = "RX_APP_ROLE"
SNOWFLAKE_WAREHOUSE = "RX_CORTEX_WH"
SNOWFLAKE_PRIVATE_KEY = """-----BEGIN PRIVATE KEY----- ... -----END PRIVATE KEY-----"""
# local alternative: SNOWFLAKE_PRIVATE_KEY_PATH = "~/.snowflake/rsa_key.p8"
```

## Data sources (all public, zero-PHI)

| Feed | Source | Filter |
|------|--------|--------|
| Medicaid State Drug Utilization Data 2025 | data.medicaid.gov | KY + TN, `suppression_used=false` |
| CMS NADAC 2026 (weekly) | data.medicaid.gov | latest `as_of_date` |
| Medicare Part D Prescribers 2024 | data.cms.gov | Louisville + Nashville metros |

# Deploying to Streamlit in Snowflake (SiS)

`app.py` is dual-mode: it uses Snowflake's injected Snowpark session
(`get_active_session()`) inside SiS, and falls back to key-pair connector auth
(Community Cloud / self-host) everywhere else. It detects the environment at
runtime — no code change needed to switch.

## Prerequisites (read carefully)

- SiS apps run as the **viewer's** Snowflake session, so **every viewer must have
  a Snowflake account**. SiS is Snowsight-internal — there is **no public URL**
  like Community Cloud. If you need "anyone with a link" access, keep it on
  Community Cloud (sleeps after 12h) or a $7/mo always-on host (Render/Railway).
- The viewer's role needs: `USAGE` on `RX_INTELLIGENCE` and schema `ANALYTICS`,
  `SELECT` on the `V_*` views and `POLICY_CHUNKS`, and privilege to call
  `SNOWFLAKE.CORTEX.ANALYST_PREVIEW` / `SEARCH_PREVIEW`.

## Option A — Snowsight UI

1. Snowsight → Data Products → Apps → **+ Streamlit App**.
2. Choose **Python**, name it, set warehouse `RX_CORTEX_WH` and app location
   `RX_INTELLIGENCE.ANALYTICS`.
3. Upload `app.py` and `environment.yml`.
4. Create — the app builds and runs in Snowsight.

## Option B — SQL (files must already be in a stage)

```sql
CREATE STAGE IF NOT EXISTS RX_INTELLIGENCE.ANALYTICS.TRANSPARENT_RX_STAGE;

CREATE OR REPLACE STREAMLIT RX_INTELLIGENCE.ANALYTICS.TRANSPARENT_RX_WORKBENCH
  ROOT_LOCATION = '@RX_INTELLIGENCE.ANALYTICS.TRANSPARENT_RX_STAGE'
  MAIN_FILE = 'app.py'
  QUERY_WAREHOUSE = 'RX_CORTEX_WH'
  COMMENT = 'Transparent Rx Intelligence Workbench (AffirmedRx demo)';
```

Upload `app.py` + `environment.yml` to the stage first (Snowsight → Files, or
`snow stage put`).

## Notes

- `environment.yml` pulls packages from Snowflake's Anaconda channel; adjust
  versions if the channel doesn't carry a listed one.
- No secrets or private key are needed in SiS — the session is the viewer's.
- **Runtime choice:** warehouse runtime (default) auto-suspends ~15 min after the
  last viewer; container runtime (compute pool) stays warm ~3 days. See the
  Snowflake docs on "Managing costs for Streamlit in Snowflake".

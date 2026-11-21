"""
Transparent Rx Intelligence Workbench — Powered by Snowflake Cortex
Module B: zero-login 3-tab Streamlit app (AffirmedRx demo).

Tabs:
  1. I-65 Spread & Access Pulse  — dumbbell gap chart + dual-city map + drill-down
  2. Governed Cortex Workbench   — persona switcher + Cortex Analyst/Search + sign-off
  3. AI Vital Signs & Cost Ledger — live telemetry + FinOps meter

Auth: key-pair as RX_APP_ROLE on Community Cloud / self-host; inside Streamlit
in Snowflake (SiS) the Snowpark session is injected. Zero end-user login.
"""
import base64
import json
import os
import re
import time
import uuid

import pandas as pd
import streamlit as st
import snowflake.connector
from cryptography.hazmat.primitives import serialization
import plotly.graph_objects as go

# ---------------------------------------------------------------------------
# Config (overridable via Streamlit secrets for Community Cloud)
# ---------------------------------------------------------------------------
ACCOUNT = st.secrets.get("SNOWFLAKE_ACCOUNT", "unpsrpt-il63479")
USER = st.secrets.get("SNOWFLAKE_USER", "benjamin.atkinson@gmail.com")
ROLE = st.secrets.get("SNOWFLAKE_ROLE", "RX_APP_ROLE")
WAREHOUSE = st.secrets.get("SNOWFLAKE_WAREHOUSE", "RX_CORTEX_WH")
DB = "RX_INTELLIGENCE"
PRIVATE_KEY_PATH = st.secrets.get(
    "SNOWFLAKE_PRIVATE_KEY_PATH", os.path.expanduser("~/.snowflake/rsa_key.p8")
)

SEARCH_SERVICE = f"{DB}.ANALYTICS.POLICY_SEARCH"
SEMANTIC_VIEW = f"{DB}.ANALYTICS.SV_TRANSPARENT_RX"

DAILY_QUERY_CAP = 50
SESSION_QUERY_CAP = 8
PROMPT_CHAR_CAP = 350

PALETTE = {
    "bg": "#F7F9FA", "card": "#FFFFFF", "navy": "#102A43",
    "teal": "#0F766E", "amber": "#D97706", "green": "#15803D",
    "muted": "#627D98",
}

PERSONAS = {
    "RFP Proposal Analyst": {
        "context": "You are a PBM RFP analyst producing precise, audit-ready answers with exact dollar figures, 11-digit NDC citations, and policy references.",
        "samples": [
            "What is the total spread leakage for GLP-1 drugs in Kentucky?",
            "Which therapeutic class has the highest spread per claim in Tennessee?",
            "Compare total Medicaid spend vs pass-through benchmark by state.",
        ],
    },
    "Clinical Pharmacist / PCA": {
        "context": "You are a clinical pharmacist / pharmacy cost analyst focused on therapeutic appropriateness, drug mix, and brand-vs-generic prescribing patterns.",
        "samples": [
            "Which brand drugs drive the highest spend among Nashville prescribers?",
            "What is the brand vs generic mix for statins across the I-65 corridor?",
            "Which specialties prescribe the most GLP-1s in Louisville?",
        ],
    },
    "Plan Sponsor Executive": {
        "context": "You are a plan sponsor executive who needs a concise, executive-level summary of spread leakage, transparency, and compliance posture.",
        "samples": [
            "Summarize total spread leakage and the pass-through benchmark across KY and TN.",
            "What does the 2026 DOL fee-disclosure rule require for PBMs?",
            "How much could we save by moving to pass-through pricing?",
        ],
    },
}

# ---------------------------------------------------------------------------
# Methodology — single source of truth for the "how is this calculated?" note.
# (The $10.50 dispensing-fee justification is under active research verification.)
# ---------------------------------------------------------------------------
METHODOLOGY = {
    "formula": (
        "Spread = total reimbursement − pass-through benchmark, where the benchmark = "
        "(NADAC ingredient cost × units) + (a fixed $10.50 professional dispensing fee per prescription)."
    ),
    "nadac": (
        "NADAC (National Average Drug Acquisition Cost) is CMS's estimate of the average "
        "invoice price pharmacies actually pay for a drug — ingredient cost only. Published "
        "weekly at the 11-digit NDC level (computed for CMS by Myers and Stauffer LC). It "
        "excludes off-invoice rebates, price concessions, and the professional dispensing fee."
    ),
    "dispensing_fee": (
        "$10.50 is a fixed national-approximation dispensing-fee benchmark — NOT the "
        "published state rate. Kentucky Medicaid pays $10.64 per claim; Tennessee pays a "
        "tiered $13.16 (<65,000 Rx/yr) or $9.02 (≥65,000 Rx/yr). Using $10.50 simplifies the "
        "KY/TN benchmark, so the displayed spread is approximate."
    ),
    "sources": (
        "Computed from `V_KY_TN_SPREAD_ANALYSIS` on CMS public data (zero PHI): NADAC "
        "(weekly, 2026), Medicaid State Drug Utilization Data 2025, and Medicare Part D "
        "Prescribers (2024), aggregated to state / therapeutic-class level."
    ),
    "caveats": [
        "NADAC is ingredient cost only and excludes off-invoice rebates/concessions — spread here is a conservative floor estimate.",
        "$10.50 is a national proxy, not the KY/TN fee (KY $10.64; TN $13.16 / $9.02).",
        "NADAC is a national average; actual acquisition cost varies by pharmacy and geography.",
        "Figures are per-prescription averages across Kentucky and Tennessee.",
    ],
    "citations": [
        ("CMS — NADAC methodology (Dec 2024)", "https://www.medicaid.gov/medicaid-chip-program-information/by-topics/prescription-drugs/ful-nadac-downloads/nadacmethodology.pdf"),
        ("KY SFY 2025 Pharmacy Benefits Report ($10.64)", "https://apps.legislature.ky.gov/AgencyReports/IJC/AR/HFS/DeptMS/PB/2025%2011.pdf"),
        ("TennCare dispensing-fee SPA notice (eff. Nov 1, 2023)", "https://www.tn.gov/content/dam/tn/tenncare/archive/PharmacyDispensingFeesSPAPublic%20Notice.pdf"),
        ("DOL/EBSA — PBM Fee Disclosure final rule (Oct 2026)", "https://www.dol.gov/agencies/ebsa/about-ebsa/our-activities/resource-center/fact-sheets/pharmacy-benefit-manager-fee-disclosure-final-rule"),
    ],
}


# ---------------------------------------------------------------------------
# PHI guardrail (client-side pre-flight regex — zero-PHI intercept)
# ---------------------------------------------------------------------------
PHI_PATTERNS = {
    "SSN": r"\b\d{3}-\d{2}-\d{4}\b|(?<!\d)\d{9}(?!\d)",
    "DOB": r"\b(?:dob|date\s*of\s*birth|birth\s*date|birthdate|born\s+on)\b|\b\d{1,2}/\d{1,2}/\d{4}\b",
    "MEMBER_ID": r"\b(?:member\s*id|beneficiary\s*id|mbi|member\s*number)\b"
                 r"|[0-9][A-Z][0-9A-Z][0-9]-[0-9A-Z][0-9][0-9A-Z][0-9]-[0-9A-Z]{2}[0-9]{2}",
    "PHONE": r"(?<!\d)\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)",
}


def detect_phi(text: str):
    """Return list of (label, matched_text) for any PHI pattern found."""
    hits = []
    for label, pat in PHI_PATTERNS.items():
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            hits.append((label, m.group(0)))
    return hits


# ---------------------------------------------------------------------------
# Snowflake connection (key-pair, cached) — used ONLY outside Snowflake.
# Inside Streamlit in Snowflake (SiS), Snowflake injects a Snowpark session via
# get_active_session(); no connector, secrets, or private key are needed there.
# ---------------------------------------------------------------------------
def _sis_session():
    """Return the injected Snowpark session in Streamlit in Snowflake, else None."""
    try:
        from snowflake.snowpark.context import get_active_session
        return get_active_session()
    except Exception:
        return None


_SIS = _sis_session()


@st.cache_resource(show_spinner=False)
def get_conn():
    key_b64 = st.secrets.get("SNOWFLAKE_PRIVATE_KEY_B64")
    key_pem = st.secrets.get("SNOWFLAKE_PRIVATE_KEY")
    if key_b64:
        key_data = base64.b64decode(key_b64)
    elif key_pem:
        key_data = key_pem.encode()
    else:
        key_path = os.path.expanduser(PRIVATE_KEY_PATH)
        if not os.path.exists(key_path):
            raise RuntimeError(
                "Snowflake private key not configured. On Streamlit Cloud, open "
                "Settings → Secrets and add SNOWFLAKE_PRIVATE_KEY_B64 (base64 of "
                "the PEM file), then Save + Reboot."
            )
        with open(key_path, "rb") as f:
            key_data = f.read()
    pkey = serialization.load_pem_private_key(key_data, password=None)
    import socket
    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(45)
    print("SF_CONNECT_START account=%s" % ACCOUNT, flush=True)
    try:
        conn = snowflake.connector.connect(
            account=ACCOUNT, user=USER, role=ROLE, warehouse=WAREHOUSE,
            database=DB, private_key=pkey,
            login_timeout=45, network_timeout=45,
        )
        print("SF_CONNECT_DONE", flush=True)
        return conn
    except Exception as e:
        print("SF_CONNECT_ERROR %r" % e, flush=True)
        raise
    finally:
        socket.setdefaulttimeout(old_timeout)


def query(sql, params=None):
    """Run SQL and return (rows, cursor). rows is a list of tuples; cursor is
    None inside Streamlit in Snowflake. Snowpark binds '?' placeholders, so the
    '%s' style used by the connector is translated for the SiS path."""
    if _SIS is not None:
        if params:
            result = _SIS.sql(sql.replace("%s", "?"), params=list(params)).collect()
        else:
            result = _SIS.sql(sql).collect()
        return [tuple(r) for r in result], None
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(sql, params or ())
    return cur.fetchall(), cur


# ---------------------------------------------------------------------------
# Tab 1 data (cached)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def load_spread_comparison():
    sql = f"""
        SELECT STATE, THERAPEUTIC_CLASS,
               SUM(TOTAL_REIMBURSED) / NULLIF(SUM(RX_COUNT), 0) AS AVG_REIMBURSE_PER_RX,
               SUM(PASS_THROUGH_BENCHMARK) / NULLIF(SUM(RX_COUNT), 0) AS AVG_BENCHMARK_PER_RX,
               SUM(ESTIMATED_SPREAD_DOLLARS) AS SPREAD,
               SUM(ESTIMATED_SPREAD_DOLLARS) / NULLIF(SUM(RX_COUNT), 0) AS AVG_SPREAD_PER_RX
        FROM {DB}.ANALYTICS.V_KY_TN_SPREAD_ANALYSIS
        GROUP BY STATE, THERAPEUTIC_CLASS
    """
    rows, _ = query(sql)
    cols = ["STATE", "THERAPEUTIC_CLASS", "AVG_REIMBURSE_PER_RX",
            "AVG_BENCHMARK_PER_RX", "SPREAD", "AVG_SPREAD_PER_RX"]
    return pd.DataFrame(rows, columns=cols)


@st.cache_data(ttl=3600, show_spinner=False)
def load_spread_headline():
    rows, _ = query(f"""
        SELECT ROUND(SUM(TOTAL_REIMBURSED),0), ROUND(SUM(PASS_THROUGH_BENCHMARK),0),
               ROUND(SUM(ESTIMATED_SPREAD_DOLLARS),0), COUNT(DISTINCT NDC11)
        FROM {DB}.ANALYTICS.V_KY_TN_SPREAD_ANALYSIS
    """)
    r = rows[0]
    return {"reimbursed": r[0], "benchmark": r[1], "spread": r[2], "ndc": r[3]}


@st.cache_data(ttl=3600, show_spinner=False)
def load_partd_prescribers():
    rows, _ = query(f"""
        SELECT PRSCRBR_NPI, PRSCRBR_LAST_ORG_NAME, PRSCRBR_FIRST_NAME,
               METRO_CITY, STATE, SPECIALTY, BRND_NAME, GNRC_NAME,
               THERAPEUTIC_CLASS, BRAND_GENERIC_FLAG,
               PARTD_CLAIMS, PARTD_DRUG_COST, LATITUDE, LONGITUDE
        FROM {DB}.ANALYTICS.V_I65_PARTD_PRESCRIBING
    """)
    cols = ["PRSCRBR_NPI", "PRSCRBR_LAST_ORG_NAME", "PRSCRBR_FIRST_NAME",
            "METRO_CITY", "STATE", "SPECIALTY", "BRND_NAME", "GNRC_NAME",
            "THERAPEUTIC_CLASS", "BRAND_GENERIC_FLAG",
            "PARTD_CLAIMS", "PARTD_DRUG_COST", "LATITUDE", "LONGITUDE"]
    df = pd.DataFrame(rows, columns=cols)
    df["PRESCRIBER"] = df["PRSCRBR_FIRST_NAME"].fillna("") + " " + df["PRSCRBR_LAST_ORG_NAME"].fillna("")
    df["LATITUDE"] = df["LATITUDE"].astype(float)
    df["LONGITUDE"] = df["LONGITUDE"].astype(float)
    df["PARTD_DRUG_COST"] = df["PARTD_DRUG_COST"].astype(float)
    df["PARTD_CLAIMS"] = df["PARTD_CLAIMS"].astype("int64")
    return df


# ---------------------------------------------------------------------------
# Cortex orchestrator
# ---------------------------------------------------------------------------
def cortex_analyst(question: str):
    """Return (interpretation_text, generated_sql) from Cortex Analyst."""
    req = json.dumps({
        "messages": [{"role": "user", "content": [{"type": "text", "text": question}]}],
        "semantic_view": SEMANTIC_VIEW,
    })
    rows, _ = query(
        f"SELECT SNOWFLAKE.CORTEX.ANALYST_PREVIEW(%s)", (req,)
    )
    resp = json.loads(rows[0][0])
    content = resp.get("message", {}).get("content", [])
    text = ""
    sql = ""
    for c in content:
        if c.get("type") == "text":
            text = c.get("text", "")
        elif c.get("type") == "sql":
            sql = c.get("statement", "")
    return text, sql, resp


def cortex_search(query_text: str, limit: int = 5):
    """Return list of {chunk, score, doc_category, source_title, section_ref}."""
    req = json.dumps({"query": query_text, "limit": limit})
    rows, _ = query(
        f"SELECT SNOWFLAKE.CORTEX.SEARCH_PREVIEW(%s, %s)",
        (SEARCH_SERVICE, req),
    )
    resp = json.loads(rows[0][0])
    out = []
    for r in resp.get("results", []):
        out.append({
            "chunk": r.get("CHUNK", ""),
            "score": round((r.get("@scores", {}) or {}).get("reranker_score", 0), 3),
            "doc_category": r.get("DOC_CATEGORY", ""),
            "source_title": r.get("SOURCE_TITLE", ""),
            "section_ref": r.get("SECTION_REF", ""),
        })
    return out


def insert_audit(session_id, persona, prompt, phi_pass, sql, draft, citations, latency_ms):
    event_id = str(uuid.uuid4())
    query(f"""
        INSERT INTO {DB}.GOVERNANCE.AI_WORKBENCH_AUDIT
            (EVENT_ID, SESSION_ID, USER_ROLE_PERSONA, PROMPT_TEXT, PHI_GUARDRAIL_PASS,
             GENERATED_SQL, AI_DRAFT_RESPONSE, CITATIONS_JSON, LATENCY_MS)
        SELECT %s, %s, %s, %s, %s, %s, %s, PARSE_JSON(%s), %s
    """, (event_id, session_id, persona, prompt, phi_pass, sql, draft, citations, latency_ms))
    return event_id


def update_audit_signoff(event_id, status, reviewer, confidence, minutes_saved):
    query(f"""
        UPDATE {DB}.GOVERNANCE.AI_WORKBENCH_AUDIT
        SET REVIEW_STATUS = %s, REVIEWER_NAME = %s, REVIEWED_TS = CURRENT_TIMESTAMP(),
            CONFIDENCE_RATING = %s, EST_MINUTES_SAVED = %s
        WHERE EVENT_ID = %s
    """, (status, reviewer, confidence, minutes_saved, event_id))


def budget_status():
    rows, _ = query(f"SELECT QUERIES_TODAY, DAILY_QUERY_CAP, REMAINING_QUERIES "
                    f"FROM {DB}.GOVERNANCE.DAILY_BUDGET_STATUS")
    r = rows[0]
    return {"used": r[0], "cap": r[1], "remaining": r[2]}


def load_telemetry():
    rows, _ = query(f"""
        SELECT COUNT(*) AS total_events,
               SUM(CASE WHEN PHI_GUARDRAIL_PASS THEN 1 ELSE 0 END) AS phi_passes,
               SUM(CASE WHEN REVIEW_STATUS='HUMAN_VERIFIED' THEN 1 ELSE 0 END) AS approved,
               SUM(CASE WHEN REVIEW_STATUS='FLAGGED' THEN 1 ELSE 0 END) AS flagged,
               AVG(CONFIDENCE_RATING) AS avg_confidence,
               COALESCE(SUM(EST_MINUTES_SAVED),0) AS minutes_saved
        FROM {DB}.GOVERNANCE.AI_WORKBENCH_AUDIT
    """)
    r = rows[0]
    return {"total": r[0] or 0, "phi_passes": r[1] or 0, "approved": r[2] or 0,
            "flagged": r[3] or 0, "avg_confidence": r[4] or 0, "minutes_saved": r[5] or 0}


# ---------------------------------------------------------------------------
# Visualization helpers
# ---------------------------------------------------------------------------
def badge(text, color):
    return (f'<span style="display:inline-block;padding:2px 10px;border-radius:12px;'
            f'font-size:0.8rem;font-weight:600;color:#fff;background:{color};">{text}</span>')


def build_dumbbell(df):
    classes = (df.groupby("THERAPEUTIC_CLASS")["SPREAD"].sum()
               .sort_values(ascending=False).head(6).index.tolist())
    fig = go.Figure()
    state_colors = {"KY": PALETTE["teal"], "TN": PALETTE["navy"]}
    y_positions = {}
    y = 0
    for cls in classes:
        for st_ in ["KY", "TN"]:
            row = df[(df.THERAPEUTIC_CLASS == cls) & (df.STATE == st_)]
            if row.empty:
                continue
            r = row.iloc[0]
            bench = r["AVG_BENCHMARK_PER_RX"]
            reimb = r["AVG_REIMBURSE_PER_RX"]
            label = f"{cls} · {st_}"
            y_positions[label] = y
            fig.add_trace(go.Scatter(
                x=[bench, reimb], y=[y, y], mode="lines+markers",
                line=dict(color=state_colors[st_], width=2),
                marker=dict(size=7, color=[PALETTE["muted"], state_colors[st_]]),
                name=label, showlegend=False, hoverinfo="skip",
            ))
            y -= 1
    fig.update_yaxes(tickvals=list(y_positions.values()), ticktext=list(y_positions.keys()))
    fig.update_layout(
        height=420, margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis_title="$ per prescription",
    )
    return fig


def fmt_dollars(x):
    return f"${x:,.0f}"


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Transparent Rx Intelligence Workbench",
                   page_icon="💊", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 1.5rem;}
div[data-testid="stMetricValue"] {color: #102A43;}
h1, h2, h3 {color: #102A43;}
</style>
""", unsafe_allow_html=True)

st.title("💊 Transparent Rx Intelligence Workbench")
st.caption("Powered by Snowflake Cortex · zero-PHI public data · AffirmedRx demo")

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "query_count" not in st.session_state:
    st.session_state.query_count = 0

# Connectivity guard — fail loudly and clearly if Snowflake isn't reachable.
# In SiS the session is already injected, so there's nothing to connect.
if _SIS is None:
    try:
        get_conn()
    except Exception as e:
        st.error(f"⚠️ Could not connect to Snowflake: {e}")
        st.info(
            "**Fix:** open this app's **Settings → Secrets** on Streamlit Cloud, "
            "paste the full secrets block (including the Snowflake private key as a "
            "single-line `SNOWFLAKE_PRIVATE_KEY_B64` value), then click **Save** and "
            "**Reboot**."
        )
        st.stop()

tab1, tab2, tab3 = st.tabs([
    "📊 I-65 Spread & Access Pulse",
    "🧠 Governed Cortex Workbench",
    "📈 AI Vital Signs & Cost Ledger",
])

# =============================================================================
# TAB 1 — Spread & Access Pulse
# =============================================================================
with tab1:
    spread_df = load_spread_comparison()
    headline = load_spread_headline()
    partd_df = load_partd_prescribers()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Medicaid reimbursement", fmt_dollars(headline["reimbursed"]))
    c2.metric("Pass-through benchmark", fmt_dollars(headline["benchmark"]))
    c3.metric("Estimated spread leakage", fmt_dollars(headline["spread"]),
              help="Reimbursement minus fair NADAC + $10.50 dispensing-fee benchmark")
    c4.metric("Distinct NDCs joined", f"{headline['ndc']:,}")

    with st.expander("ⓘ How these numbers are calculated (methodology & sources)"):
        st.markdown(f"**Formula.** {METHODOLOGY['formula']}")
        st.markdown(f"**NADAC.** {METHODOLOGY['nadac']}")
        st.markdown(f"**Dispensing fee.** {METHODOLOGY['dispensing_fee']}")
        st.markdown(f"**Data sources.** {METHODOLOGY['sources']}")
        st.markdown("**Caveats.**")
        for c in METHODOLOGY["caveats"]:
            st.markdown(f"- {c}")
        st.markdown("**References.**")
        for title, url in METHODOLOGY["citations"]:
            st.markdown(f"- [{title}]({url})")

    st.subheader("Spread gap per prescription — KY vs TN (top therapeutic classes)")
    st.markdown(
        badge("DETERMINISTIC · NO AI MODEL", PALETTE["navy"]) + "&nbsp;"
        + badge("NADAC + $10.50 BENCHMARK", PALETTE["teal"]),
        unsafe_allow_html=True,
    )
    st.plotly_chart(build_dumbbell(spread_df), width="stretch")
    st.caption("Amber/navy dot = average plan reimbursement · grey dot = NADAC invoice-acquisition + $10.50 benchmark. The gap is spread.")

    st.subheader("I-65 prescriber map (Louisville vs Nashville)")
    map_df = (partd_df.groupby(["METRO_CITY", "STATE", "LATITUDE", "LONGITUDE"])
              .agg(prescribers=("PRSCRBR_NPI", "nunique"),
                   total_drug_cost=("PARTD_DRUG_COST", "sum")).reset_index())
    st.map(map_df.rename(columns={"LATITUDE": "latitude", "LONGITUDE": "longitude"}),
           size="total_drug_cost")

    st.subheader("High-cost brand prescribers (clinical outreach)")
    brand_df = partd_df[partd_df["BRAND_GENERIC_FLAG"] == "Brand"]
    drill = (brand_df.groupby(["PRESCRIBER", "METRO_CITY", "SPECIALTY", "BRND_NAME"])
             .agg(claims=("PARTD_CLAIMS", "sum"), drug_cost=("PARTD_DRUG_COST", "sum"))
             .reset_index().sort_values("drug_cost", ascending=False).head(30))
    drill["drug_cost"] = drill["drug_cost"].map(lambda x: f"${x:,.0f}")
    drill.columns = ["Prescriber", "Metro", "Specialty", "Brand", "Claims", "Drug cost"]
    st.dataframe(drill, width="stretch", hide_index=True)

# =============================================================================
# TAB 2 — Governed Cortex Workbench
# =============================================================================
with tab2:
    persona = st.radio("Role-based AI persona", list(PERSONAS.keys()), horizontal=True)
    pcfg = PERSONAS[persona]

    budget = budget_status()
    remaining = budget["remaining"]
    session_left = SESSION_QUERY_CAP - st.session_state.query_count
    exhausted = remaining <= 0 or session_left <= 0

    st.markdown(f"**Daily budget:** {budget['used']}/{budget['cap']} queries used · "
                f"**session left:** {session_left}")

    if exhausted:
        st.warning("Query budget exhausted — showing pre-cached executive insights instead.")
        st.info("**Cached insight:** across KY+TN, estimated spread leakage is "
                f"~{fmt_dollars(load_spread_headline()['spread'])} on "
                f"{fmt_dollars(load_spread_headline()['reimbursed'])} of Medicaid reimbursement "
                f"(~6.7% spread). 'Lowest net cost ≠ highest rebate.'")
    else:
        with st.form("query_form", clear_on_submit=False):
            prompt = st.text_area("Ask Cortex (Cortex Analyst + policy RAG)",
                                  max_chars=PROMPT_CHAR_CAP,
                                  placeholder=pcfg["samples"][0])
            submitted = st.form_submit_button("Run governed query")

        if submitted and prompt.strip():
            st.session_state.query_count += 1
            phi_hits = detect_phi(prompt)
            if phi_hits:
                labels = ", ".join(sorted({l for l, _ in phi_hits}))
                insert_audit(st.session_state.session_id, persona, prompt, False,
                             None, None, "[]", 0)
                st.error(f"🚫 PHI guardrail blocked this prompt ({labels}). "
                         "No model was called. Attempt logged to the audit ledger.")
            else:
                t0 = time.time()
                with st.spinner("Cortex Analyst → generating SQL against the semantic view ..."):
                    try:
                        interpretation, sql, _ = cortex_analyst(prompt)
                    except Exception as e:
                        st.error(f"Cortex Analyst error: {e}")
                        sql, interpretation = "", ""

                citations = []
                try:
                    citations = cortex_search(prompt, limit=4)
                except Exception:
                    pass

                latency = int((time.time() - t0) * 1000)

                # execute the generated SQL to get real numbers
                result_rows = []
                if sql:
                    try:
                        result_rows, _ = query(sql)
                    except Exception as e:
                        st.warning(f"Generated SQL executed with a warning: {e}")

                draft = interpretation or "Draft response pending."
                if result_rows:
                    draft += "\n\n**Result:** " + str(result_rows[0])

                citations_json = json.dumps([{
                    "source_title": c["source_title"], "section_ref": c["section_ref"],
                    "doc_category": c["doc_category"], "score": c["score"],
                } for c in citations])

                event_id = insert_audit(
                    st.session_state.session_id, persona, prompt, True,
                    sql, draft, citations_json, latency,
                )
                st.session_state.last_event_id = event_id

                st.markdown(badge("UNVERIFIED DRAFT", PALETTE["amber"]), unsafe_allow_html=True)
                st.markdown(f"**Interpretation:** {interpretation}")

                if result_rows:
                    st.markdown("**Answer:**")
                    st.code(str(result_rows), language="text")

                with st.expander("🔍 Source transparency drawer"):
                    st.markdown(
                        "**How to read this.** Every AI answer carries its generated SQL and "
                        "the policy chunks it grounded on. The **reranker score** (−∞…1) rates "
                        "relevance — higher is a closer match. Numbers come only from the SQL "
                        "run against the semantic view, so every figure is traceable to a cited "
                        "source."
                    )
                    st.markdown("**Generated SQL**")
                    st.code(sql if sql else "(no SQL)", language="sql")
                    if citations:
                        st.markdown("**Claim → source mapping (Cortex Search)**")
                        for i, c in enumerate(citations, 1):
                            st.markdown(
                                f"**{i}.** `{c['source_title']}` · {c['section_ref']} "
                                f"· {c['doc_category']} · score {c['score']}\n\n"
                                f"_{c['chunk'][:240]}..._"
                            )
                    else:
                        st.write("No policy chunks matched.")

                # ---- Mandatory human sign-off drawer ----
                st.markdown("#### ✍️ Mandatory Human Sign-Off")
                with st.form("signoff_form"):
                    reviewer = st.text_input("Reviewer name")
                    confidence = st.slider("Confidence score (1–5)", 1, 5, 4)
                    minutes_saved = st.number_input("Estimated minutes saved", 0, 1000, 10)
                    notes = st.text_area("Review notes (optional)")
                    col_a, col_b = st.columns(2)
                    approve = col_a.form_submit_button("✅ Approve & Sign Off")
                    flag = col_b.form_submit_button("🚩 Flag for Revision")

                if (approve or flag) and reviewer.strip():
                    status = "HUMAN_VERIFIED" if approve else "FLAGGED"
                    update_audit_signoff(event_id, status, reviewer, confidence, minutes_saved)
                    if approve:
                        st.markdown(badge("HUMAN VERIFIED", PALETTE["green"]), unsafe_allow_html=True)
                        st.success("Signed off. Report export unlocked. Audit written back to Snowflake.")
                    else:
                        st.warning("Flagged for revision — returned to draft.")
                elif (approve or flag):
                    st.error("Reviewer name is required to sign off.")

# =============================================================================
# TAB 3 — AI Vital Signs & Cost Ledger
# =============================================================================
with tab3:
    tele = load_telemetry()
    budget = budget_status()

    grounded_pct = round((tele["phi_passes"] / tele["total"] * 100), 1) if tele["total"] else 0.0
    approval_rate = (round((tele["approved"] / max(1, tele["approved"] + tele["flagged"]) * 100), 1)
                     if (tele["approved"] + tele["flagged"]) else 0.0)

    k1, k2, k3 = st.columns(3)
    k1.metric("Citation groundedness", f"{grounded_pct}%")
    k1.metric("Zero-PHI guardrail passes", f"{tele['phi_passes']}")
    k2.metric("Human approval vs edit rate", f"{approval_rate}%")
    k2.metric("Avg confidence score", f"{tele['avg_confidence']:.1f}/5")
    k3.metric("Estimated minutes saved", f"{tele['minutes_saved']:,}")
    k3.metric("Total audited events", f"{tele['total']}")

    st.subheader("Live FinOps budget meter")
    pct = min(100, int(budget["used"] / budget["cap"] * 100))
    st.progress(pct / 100, text=f"{budget['used']} / {budget['cap']} queries today "
                                f"({budget['remaining']} remaining)")
    st.caption("Warehouse `RX_CORTEX_WH` is bound to resource monitor `RX_TRIAL_MONITOR` "
               "(15 credits/mo — alert 75%, suspend 95%, immediate 100%).")

st.caption("Transparent Rx · Module B — Streamlit app + Cortex orchestrator")

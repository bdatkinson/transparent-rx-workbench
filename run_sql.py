#!/usr/bin/env python3
"""Run a .sql file statement-by-statement against Snowflake via key-pair auth."""
import sys, os
import snowflake.connector
from cryptography.hazmat.primitives import serialization

def get_conn():
    with open(os.path.expanduser("~/.snowflake/rsa_key.p8"), "rb") as f:
        pkey = serialization.load_pem_private_key(f.read(), password=None)
    return snowflake.connector.connect(
        account="unpsrpt-il63479",
        user="benjamin.atkinson@gmail.com",
        role="ACCOUNTADMIN",
        warehouse="RX_CORTEX_WH",
        private_key=pkey,
    )

def split_statements(sql_text):
    """Naive split on ';' at line ends; strips comments/blank lines."""
    stmts, buf = [], []
    for line in sql_text.splitlines():
        s = line.strip()
        if s.startswith("--") or s == "":
            continue
        buf.append(line)
        if s.rstrip().endswith(";"):
            stmts.append("\n".join(buf).rstrip(";").strip())
            buf = []
    if "".join(buf).strip():
        stmts.append("\n".join(buf).strip())
    return [s for s in stmts if s]

def main():
    path = sys.argv[1]
    sql = open(path).read()
    stmts = split_statements(sql)
    print(f"[{path}] {len(stmts)} statements", flush=True)
    conn = get_conn()
    cur = conn.cursor()
    try:
        for i, stmt in enumerate(stmts, 1):
            first = " ".join(stmt.split())[:70]
            try:
                cur.execute(stmt)
                n = cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0
                print(f"  [{i}/{len(stmts)}] OK ({n} rows) :: {first}", flush=True)
            except Exception as e:
                print(f"  [{i}/{len(stmts)}] FAIL :: {first}\n      {str(e).strip()[:400]}", flush=True)
                raise
    finally:
        conn.close()

if __name__ == "__main__":
    main()

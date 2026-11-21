#!/usr/bin/env python3
"""Render the app through Streamlit's AppTest harness to catch runtime errors."""
from streamlit.testing.v1 import AppTest

at = AppTest.from_file("app.py", default_timeout=90)
at.run()

if at.exception:
    print("!!! EXCEPTIONS !!!")
    for e in at.exception:
        print("-", e.value)
        print("  traceback:", "\n".join(e.stack_trace) if e.stack_trace else "")
else:
    print("NO EXCEPTIONS — app rendered cleanly.")

print("\n--- element summary ---")
print("tabs:", [t.label for t in at.tabs])
print("metrics:", len(at.metric))
print("dataframes:", len(at.dataframe))
print("plotly charts:", len(at.get("plotly_chart")))
print("forms:", len(at.get("form")))

# sanity: the headline metric should show the $ spread value
for m in at.metric:
    print("metric:", m.label, "=", m.value)

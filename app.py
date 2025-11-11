import streamlit as st
import pandas as pd
import io, xmltodict, re
from openai import OpenAI

# ---------- Config ----------
st.set_page_config(page_title="BPMN → AI Tag Generator", layout="wide")
st.markdown("<h2 style='text-align:center;'>BPMN → AI Tag Generator</h2>", unsafe_allow_html=True)

# ---------- Sidebar: API Status ----------
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY")
MODEL = st.secrets.get("OPENAI_MODEL", "gpt-4o-mini")

st.sidebar.header("API Status")
if OPENAI_API_KEY:
    st.sidebar.success("✅ OpenAI: Connected")
else:
    st.sidebar.error("❌ Missing OpenAI Key in Secrets")

# ---------- Utility Functions ----------
def clean_csv_text(raw: str) -> str:
    """Strip code fences, extra labels, and non-CSV artifacts."""
    raw = re.sub(r"^```.*?csv", "", raw, flags=re.IGNORECASE | re.DOTALL)
    raw = raw.replace("```", "").strip()
    raw = re.sub(r"^,+", "", raw)
    return raw

def call_openai_rows(model: str, key: str, prompt: str) -> str:
    """Call OpenAI to generate structured CSV text."""
    client = OpenAI(api_key=key)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
    )
    return clean_csv_text(resp.choices[0].message.content)

# ---------- BPMN Upload ----------
uploaded_file = st.file_uploader("Upload a .bpmn file (simple is fine — only <bpmn:task> needed)", type=["bpmn"])

if uploaded_file:
    data = xmltodict.parse(uploaded_file.read())
    tasks = []
    for proc in data["bpmn:definitions"]["bpmn:process"]:
        for el in proc.values():
            if isinstance(el, list):
                for node in el:
                    if isinstance(node, dict) and node.get("@id", "").startswith("Task"):
                        tasks.append({"element_id": node["@id"], "element_name": node.get("@name", "")})
else:
    # Fallback tiny sample
    tasks = [
        {"element_id": "Task_A", "element_name": "Capture Request"},
        {"element_id": "Task_B", "element_name": "Validate Data"},
        {"element_id": "Task_C", "element_name": "Approve Request"},
    ]

def as_tasks_bullets():
    return "\n".join(f"- {t['element_name']} ({t['element_id']})" for t in tasks)

# ---------- Helper ----------
def ensure_key():
    if not OPENAI_API_KEY:
        st.warning("Please add your OpenAI API key in Streamlit Secrets.")
        st.stop()
    return OPENAI_API_KEY

def show_table_with_download(state_key: str, columns: list, filename: str):
    df = st.session_state.get(state_key)
    if df is not None:
        st.dataframe(df, use_container_width=True)
        st.download_button(
            f"⬇️ Download {filename}",
            df.to_csv(index=False).encode("utf-8"),
            file_name=filename,
            mime="text/csv",
        )
    else:
        st.dataframe(pd.DataFrame(columns=columns), use_container_width=True)

# ---------- Tabs ----------
for key in ["kpis", "risks", "raci", "controls"]:
    st.session_state.setdefault(key, None)

tabs = st.tabs(["KPIs", "Risks", "RACI", "Controls"])

# --- KPIs ---
with tabs[0]:
    st.markdown("Generate **KPI** rows for each task.")
    cols = ["element_id","element_name","kpi_key","current_value","target_value","owner","last_updated"]
    if st.button("Generate KPIs"):
        key = ensure_key()
        prompt = f"""Generate a CSV table for KPIs per task below.

Tasks:
{as_tasks_bullets()}

Columns: {', '.join(cols)}.
Return only CSV rows (no markdown, no explanation)."""
        try:
            csv_text = call_openai_rows(MODEL, key, prompt)
            st.session_state["kpis"] = pd.read_csv(io.StringIO(csv_text))
        except Exception as e:
            st.error(f"CSV parsing failed: {e}")
    show_table_with_download("kpis", cols, "kpis.csv")

# --- Risks ---
with tabs[1]:
    st.markdown("Generate **Risk Register** rows linked to tasks.")
    cols = ["element_id","element_name","risk_description","risk_category","likelihood_1to5","impact_1to5","mitigation_owner","control_ref"]
    if st.button("Generate Risks"):
        key = ensure_key()
        prompt = f"""Generate a CSV risk register for these process tasks:
{as_tasks_bullets()}

Columns: {', '.join(cols)}.
Ensure consistent commas and one header only.
Return pure CSV (no ```csv markers)."""
        try:
            csv_text = call_openai_rows(MODEL, key, prompt)
            st.session_state["risks"] = pd.read_csv(io.StringIO(csv_text))
        except Exception as e:
            st.error(f"CSV parsing failed: {e}")
    show_table_with_download("risks", cols, "risks.csv")

# --- RACI ---
with tabs[2]:
    st.markdown("Generate **RACI** matrix entries per task.")
    cols = ["element_id","element_name","role","responsibility_type"]
    if st.button("Generate RACI"):
        key = ensure_key()
        prompt = f"""For the following process tasks:
{as_tasks_bullets()}

Generate a CSV table for RACI roles.
Columns: {', '.join(cols)}.
Each task may have multiple rows for different roles (R/A/C/I)."""
        try:
            csv_text = call_openai_rows(MODEL, key, prompt)
            st.session_state["raci"] = pd.read_csv(io.StringIO(csv_text))
        except Exception as e:
            st.error(f"CSV parsing failed: {e}")
    show_table_with_download("raci", cols, "raci.csv")

# --- Controls ---
with tabs[3]:
    st.markdown("Generate **Controls** mapped to tasks (SOX/ISO/etc.).")
    cols = ["element_id","element_name","control_name","control_type","frequency","evidence_required","owner"]
    if st.button("Generate Controls"):
        key = ensure_key()
        prompt = f"""Generate a CSV table for control mappings per task.
Tasks:
{as_tasks_bullets()}

Columns: {', '.join(cols)}.
Keep it clean CSV, no markdown or quotes."""
        try:
            csv_text = call_openai_rows(MODEL, key, prompt)
            st.session_state["controls"] = pd.read_csv(io.StringIO(csv_text))
        except Exception as e:
            st.error(f"CSV parsing failed: {e}")
    show_table_with_download("controls", cols, "controls.csv")











import io, json, base64, pandas as pd
import streamlit as st
from xml.etree import ElementTree as ET

st.set_page_config(page_title="BPMN → Tag Generator", page_icon="🧩", layout="wide")

# ---------- Small style to tighten layout ----------
st.markdown("""
<style>
.block-container{padding-top:1rem;padding-bottom:1rem}
#canvas{margin-bottom:.5rem;border:1px solid #ddd;border-radius:8px;height:65vh}
</style>
""", unsafe_allow_html=True)

# ---------- Helpers ----------
NS = {"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL"}

def parse_named_tasks(bpmn_xml: str):
    root = ET.fromstring(bpmn_xml.encode("utf-8"))
    out = []
    for el in root.findall(".//bpmn:task", NS):
        tid = el.attrib.get("id","")
        name = el.attrib.get("name") or el.attrib.get("{http://www.omg.org/spec/BPMN/20100524/MODEL}name","")
        if name:
            out.append({"element_id": tid, "element_name": name})
    # de-dup by id
    seen, tasks = set(), []
    for r in out:
        if r["element_id"] not in seen:
            tasks.append(r); seen.add(r["element_id"])
    return tasks

def call_openai_rows(model, api_key, prompt, temperature=0.2):
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role":"user","content":prompt}],
        temperature=temperature,
    )
    return resp.choices[0].message.content.strip()

def df_download_button(df: pd.DataFrame, label: str, filename: str):
    st.download_button(label, df.to_csv(index=False).encode("utf-8"),
                       file_name=filename, mime="text/csv")

# ---------- Sidebar: API Key + Model ----------
st.sidebar.header("AI Settings")
default_key = st.secrets.get("OPENAI_API_KEY", "")
api_key = st.sidebar.text_input("OpenAI API Key", value=("••••••" if default_key else ""), type="password")
use_secret = (api_key == "••••••" and default_key)
active_key = default_key if use_secret else (api_key if api_key and api_key!="••••••" else "")

model = st.sidebar.selectbox("Model", ["gpt-4o-mini", "gpt-4o", "gpt-4o-mini-translate"], index=0)
st.sidebar.caption("Tip: add OPENAI_API_KEY in Secrets to avoid typing here.")

# ---------- Upload BPMN ----------
st.title("BPMN → AI Tag Generator")

uploaded = st.file_uploader("Upload a .bpmn file (simple is fine — only <bpmn:task> is enough)", type=["bpmn"])
sample_exp = st.expander("Need a tiny sample?")
with sample_exp:
    st.code("""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
  xmlns:di="http://www.omg.org/spec/DD/20100524/DI"
  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
  targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="P_Simple" name="Simple Process" isExecutable="false">
    <bpmn:startEvent id="Start"/>
    <bpmn:task id="Task_A" name="Capture Request"/>
    <bpmn:task id="Task_B" name="Validate Data"/>
    <bpmn:task id="Task_C" name="Approve Request"/>
    <bpmn:endEvent id="End"/>
    <bpmn:sequenceFlow id="f1" sourceRef="Start" targetRef="Task_A"/>
    <bpmn:sequenceFlow id="f2" sourceRef="Task_A" targetRef="Task_B"/>
    <bpmn:sequenceFlow id="f3" sourceRef="Task_B" targetRef="Task_C"/>
    <bpmn:sequenceFlow id="f4" sourceRef="Task_C" targetRef="End"/>
  </bpmn:process>
</bpmn:definitions>""", language="xml")

if not uploaded:
    st.info("Upload a BPMN file to proceed.")
    st.stop()

bpmn_xml = uploaded.read().decode("utf-8", errors="ignore")
tasks = parse_named_tasks(bpmn_xml)

colL, colR = st.columns([2,1])
with colL:
    st.subheader("Process Diagram")
    # Render with bpmn-js; if no DI, auto-layout in the browser via bpmn-auto-layout UMD
    html = f"""
<div id="canvas"></div>
<script src="https://unpkg.com/bpmn-js@10.2.1/dist/bpmn-viewer.production.min.js"></script>
<script src="https://unpkg.com/bpmn-moddle@7.1.3/dist/index.umd.js"></script>
<script src="https://unpkg.com/bpmn-auto-layout@0.7.0/dist/index.umd.js"></script>
<script>
const xmlIn = {json.dumps(bpmn_xml)};
const container = document.getElementById('canvas');
const viewer = new BpmnJS({{ container }});

function hasDi(defs) {{
  try {{
    const di = defs.diagrams || [];
    return Array.isArray(di) && di.length > 0;
  }} catch(e) {{ return false; }}
}}

(async () => {{
  try {{
    await viewer.importXML(xmlIn);
    const defs = viewer.get('canvas')._diagram._definitions;
    if(!hasDi(defs)) {{
      // Auto layout if DI missing
      const moddle = new window.BpmnModdle();
      const { { rootElement } } = await moddle.fromXML(xmlIn);
      const res = await window.BpmnAutoLayout(rootElement);
      await viewer.importXML(res.xml);
    }}
    viewer.get('canvas').zoom('fit-viewport');
  }} catch(err) {{
    const pre = document.createElement('pre');
    pre.textContent = 'Render error: ' + (err && err.message ? err.message : err);
    document.body.appendChild(pre);
  }}
}})();
</script>
"""
    st.components.v1.html(html, height=520, scrolling=True)

with colR:
    st.subheader("Detected Tasks")
    if tasks:
        st.write(pd.DataFrame(tasks))
    else:
        st.warning("No named <bpmn:task> elements found. Add task names to get better AI outputs.")

st.markdown("---")

# ---------- Tabs for Tag Generators ----------
tabs = st.tabs(["KPIs", "Risks", "RACI", "Controls", "Agents"])

def ensure_key():
    if not active_key:
        st.error("Enter your OpenAI API key in the sidebar.")
        st.stop()
    return active_key

def build_task_list_md():
    return "\n".join(f"- {t['element_name']} (id: {t['element_id']})" for t in tasks) or "- (none)"

def show_result(df, filename):
    st.dataframe(df, use_container_width=True)
    df_download_button(df, "⬇️ Download CSV", filename)

# ---- KPIs ----
with tabs[0]:
    st.markdown("Generate **KPI** rows for each task.")
    if st.button("Generate KPIs"):
        key = ensure_key()
        prompt = f"""You are a BPM KPI designer.
Given these tasks:
{build_task_list_md()}

Create a CSV with columns:
element_id,element_name,kpi_key,current_value,target_value,owner,last_updated

- Use snake_case for kpi_key.
- current_value and target_value should be numeric or % where sensible.
- last_updated: YYYY-MM-DD.
Return *only* CSV rows (no markdown fences)."""
        csv_text = call_openai_rows(model, key, prompt)
        df = pd.read_csv(io.StringIO(csv_text))
        show_result(df, "kpis.csv")

# ---- Risks ----
with tabs[1]:
    st.markdown("Generate **Risk Register** rows linked to tasks.")
    if st.button("Generate Risks"):
        key = ensure_key()
        prompt = f"""You are a risk analyst.
For these tasks:
{build_task_list_md()}

Create a CSV with columns:
element_id,element_name,risk_description,risk_category,likelihood_1to5,impact_1to5,mitigation_owner,control_ref

Return only CSV rows."""
        csv_text = call_openai_rows(model, key, prompt)
        df = pd.read_csv(io.StringIO(csv_text))
        show_result(df, "risks.csv")

# ---- RACI ----
with tabs[2]:
    st.markdown("Generate **RACI** matrix entries per task.")
    if st.button("Generate RACI"):
        key = ensure_key()
        prompt = f"""You are a process governance expert.
For these tasks:
{build_task_list_md()}

Create a CSV with columns:
element_id,element_name,role,responsibility_type   # responsibility_type in [R,A,C,I]

Create 1-3 rows per task. Return only CSV rows."""
        csv_text = call_openai_rows(model, key, prompt)
        df = pd.read_csv(io.StringIO(csv_text))
        show_result(df, "raci.csv")

# ---- Controls ----
with tabs[3]:
    st.markdown("Generate **Controls** mapped to tasks (for SOX/ISO/etc.).")
    if st.button("Generate Controls"):
        key = ensure_key()
        prompt = f"""You are an internal controls specialist.
For these tasks:
{build_task_list_md()}

Create a CSV with columns:
element_id,element_name,control_name,control_type,frequency,evidence_required,owner

- control_type: Preventive/Detective/Corrective.
- frequency: e.g., per_txn, daily, weekly, monthly.
Return only CSV rows."""
        csv_text = call_openai_rows(model, key, prompt)
        df = pd.read_csv(io.StringIO(csv_text))
        show_result(df, "controls.csv")

# ---- Agents ----
with tabs[4]:
    st.markdown("Generate **AI Agent** capability map per task.")
    if st.button("Generate Agents"):
        key = ensure_key()
        prompt = f"""You are an AI solution architect.
For these tasks:
{build_task_list_md()}

Create a CSV with columns:
element_id,element_name,agent_role,capabilities,decision_logic,confidence_threshold,exception_handler,handoff_to

- confidence_threshold: 0.0-1.0
Return only CSV rows."""
        csv_text = call_openai_rows(model, key, prompt)
        df = pd.read_csv(io.StringIO(csv_text))
        show_result(df, "agents.csv")
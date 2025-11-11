import io
import json
import pandas as pd
import streamlit as st
from xml.etree import ElementTree as ET

# ---------- Page ----------
st.set_page_config(page_title="BPMN → AI Tag Generator", page_icon="🧩", layout="wide")
st.markdown("""
<style>
.block-container{padding-top:1rem;padding-bottom:1rem}
#canvas{margin-bottom:.5rem;border:1px solid #ddd;border-radius:8px;height:65vh}
.status-card{border:1px solid #E6F4EA;background:#E6F4EA;border-radius:10px;padding:.9rem 1rem;display:flex;gap:.6rem;align-items:center;margin-bottom:1rem}
.status-card.bad{border-color:#FDE0E0;background:#FDE0E0}
.status-dot{width:10px;height:10px;border-radius:50%;background:#16a34a}
.status-card.bad .status-dot{background:#dc2626}
.status-title{font-weight:600}
</style>
""", unsafe_allow_html=True)

# ---------- Config / Secrets ----------
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", "")
MODEL = st.secrets.get("OPENAI_MODEL", "gpt-4o-mini")

# ---------- Sidebar: API Status ----------
with st.sidebar:
    st.header("API Status")
    if OPENAI_API_KEY:
        st.markdown(
            '<div class="status-card"><div class="status-dot"></div>'
            '<div class="status-title">OpenAI: Connected</div></div>',
            unsafe_allow_html=True,
        )
        st.markdown(f"**Model:** `{MODEL}`")
    else:
        st.markdown(
            '<div class="status-card bad"><div class="status-dot"></div>'
            '<div class="status-title">OpenAI: Not Configured</div></div>',
            unsafe_allow_html=True,
        )
        st.caption("Add `OPENAI_API_KEY` in **Secrets** (App → Settings → Secrets).")

# ---------- Helper Function ----------
NS = {"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL"}

def parse_named_tasks(bpmn_xml: str):
    root = ET.fromstring(bpmn_xml.encode("utf-8"))
    out = []
    for el in root.findall(".//bpmn:task", NS):
        tid = el.attrib.get("id", "")
        name = el.attrib.get("name") or el.attrib.get("{http://www.omg.org/spec/BPMN/20100524/MODEL}name", "")
        if name:
            out.append({"element_id": tid, "element_name": name})
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

def require_key():
    if not OPENAI_API_KEY:
        st.error("OpenAI key is missing. Add `OPENAI_API_KEY` in Secrets to use this feature.")
        st.stop()
    return OPENAI_API_KEY

# ---------- Upload ----------
st.title("BPMN → AI Tag Generator")
uploaded = st.file_uploader("Upload a .bpmn file (simple is fine — only bpmn:task is enough)", type=["bpmn"])

# Tiny sample WITH DI (always renders)
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

  <bpmndi:BPMNDiagram id="BPMNDiagram_1">
    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="P_Simple">

      <bpmndi:BPMNShape id="Start_di" bpmnElement="Start">
        <dc:Bounds x="100" y="140" width="36" height="36"/>
      </bpmndi:BPMNShape>

      <bpmndi:BPMNShape id="Task_A_di" bpmnElement="Task_A">
        <dc:Bounds x="180" y="120" width="120" height="80"/>
      </bpmndi:BPMNShape>

      <bpmndi:BPMNShape id="Task_B_di" bpmnElement="Task_B">
        <dc:Bounds x="340" y="120" width="120" height="80"/>
      </bpmndi:BPMNShape>

      <bpmndi:BPMNShape id="Task_C_di" bpmnElement="Task_C">
        <dc:Bounds x="500" y="120" width="120" height="80"/>
      </bpmndi:BPMNShape>

      <bpmndi:BPMNShape id="End_di" bpmnElement="End">
        <dc:Bounds x="660" y="140" width="36" height="36"/>
      </bpmndi:BPMNShape>

      <bpmndi:BPMNEdge id="f1_di" bpmnElement="f1">
        <di:waypoint x="136" y="158"/>
        <di:waypoint x="180" y="158"/>
      </bpmndi:BPMNEdge>

      <bpmndi:BPMNEdge id="f2_di" bpmnElement="f2">
        <di:waypoint x="300" y="160"/>
        <di:waypoint x="340" y="160"/>
      </bpmndi:BPMNEdge>

      <bpmndi:BPMNEdge id="f3_di" bpmnElement="f3">
        <di:waypoint x="460" y="160"/>
        <di:waypoint x="500" y="160"/>
      </bpmndi:BPMNEdge>

      <bpmndi:BPMNEdge id="f4_di" bpmnElement="f4">
        <di:waypoint x="620" y="158"/>
        <di:waypoint x="660" y="158"/>
      </bpmndi:BPMNEdge>

    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>""", language="xml")

if not uploaded:
    st.info("Upload a BPMN file to proceed.")
    st.stop()

bpmn_xml = uploaded.read().decode("utf-8", errors="ignore")
tasks = parse_named_tasks(bpmn_xml)

# ---------- Render Diagram (works with/without DI) ----------
st.subheader("Process Diagram")

bpmn_html = f"""
<div id="canvas" style="height:65vh;border:1px solid #ddd;border-radius:8px;"></div>

<!-- Viewer -->
<script src="https://unpkg.com/bpmn-js@10.2.1/dist/bpmn-viewer.production.min.js"></script>

<!-- bpmn-moddle UMD -->
<script src="https://unpkg.com/bpmn-moddle@7.1.3/dist/bpmn-moddle.umd.js"></script>

<!-- Try BOTH common UMD builds for bpmn-auto-layout -->
<script src="https://cdn.jsdelivr.net/npm/bpmn-auto-layout@0.7.0/dist/bpmn-auto-layout.umd.js"></script>
<script src="https://unpkg.com/bpmn-auto-layout@0.7.0/dist/bpmn-auto-layout.umd.js"></script>

<script>
  const xmlIn = {json.dumps(bpmn_xml)};
  const viewer = new BpmnJS({{ container: '#canvas' }});

  // Resolve UMD shapes safely
  const ModdleCtor =
    (window.BpmnModdle && (window.BpmnModdle.BpmnModdle || window.BpmnModdle.default || window.BpmnModdle))
    || null;

  // May export a function or an object with a .layout function
  const autoLayoutFn =
    (window.BpmnAutoLayout && (window.BpmnAutoLayout.layout || window.BpmnAutoLayout)) ||
    (window.bpmnAutoLayout && (window.bpmnAutoLayout.layout || window.bpmnAutoLayout)) ||
    null;

  // Simple DI detection
  const hasDI = /<\\s*bpmndi:BPMNDiagram[\\s>]/.test(xmlIn);

  (async () => {{
    try {{
      if (hasDI) {{
        await viewer.importXML(xmlIn);
      }} else {{
        if (!ModdleCtor) throw new Error('BpmnModdle UMD not found');
        if (!autoLayoutFn) throw new Error('BpmnAutoLayout UMD not found');

        const moddle = new ModdleCtor();
        const res = await moddle.fromXML(xmlIn);   // {{ rootElement }}
        const rootElement = res.rootElement;       // Definitions
        const laid = await autoLayoutFn(rootElement); // -> {{ xml }}
        await viewer.importXML(laid.xml);
      }}
      viewer.get('canvas').zoom('fit-viewport');
    }} catch (err) {{
      const pre = document.createElement('pre');
      pre.style.color = '#c00';
      pre.textContent = 'Render error: ' + (err && err.message ? err.message : err);
      document.body.appendChild(pre);
    }}
  }})();
</script>
"""
st.components.v1.html(bpmn_html, height=520, scrolling=True)

# ---------- Tasks ----------
st.subheader("Detected Tasks")
if tasks:
    st.dataframe(pd.DataFrame(tasks), use_container_width=True)
else:
    st.warning("No named <bpmn:task> elements found. Add task names for better AI outputs.")

st.markdown("---")

# ---------- Tag Generators ----------
# Persist last results per tab
for _key in ["kpis", "risks", "raci", "controls", "agents"]:
    st.session_state.setdefault(_key, None)

tabs = st.tabs(["KPIs", "Risks", "RACI", "Controls", "Agents"])

def show_table_with_download(state_key: str, columns: list, download_name: str):
    """Always show a table. If we have data in session_state, show it and a download button below."""
    df = st.session_state[state_key]
    if df is None:
        st.dataframe(pd.DataFrame(columns=columns), use_container_width=True)
    else:
        st.dataframe(df, use_container_width=True)
        st.download_button(
            f"⬇️ Download {download_name}",
            df.to_csv(index=False).encode("utf-8"),
            file_name=download_name,
            mime="text/csv",
            use_container_width=False,
        )

def ensure_key():
    if not OPENAI_API_KEY:
        st.error("OpenAI key is missing. Add `OPENAI_API_KEY` in Secrets to use this feature.")
        st.stop()
    return OPENAI_API_KEY

def as_tasks_bullets():
    return "\n".join(f"- {t['element_name']} (id: {t['element_id']})" for t in tasks) or "- (none)"

# ----- KPIs -----
with tabs[0]:
    st.markdown("Generate **KPI** rows for each task.")
    cols = ["element_id","element_name","kpi_key","current_value","target_value","owner","last_updated"]
    if st.button("Generate KPIs"):
        key = ensure_key()
        prompt = f"""You are a BPM KPI designer.
Given these tasks:
{as_tasks_bullets()}

Create a CSV with columns:
{", ".join(cols)}
- Use snake_case for kpi_key.
- current_value/target_value numeric or % where sensible.
- last_updated: YYYY-MM-DD.
Return only CSV rows (no markdown fences)."""
        try:
            csv_text = call_openai_rows(MODEL, key, prompt)
            st.session_state["kpis"] = pd.read_csv(io.StringIO(csv_text))
        except Exception as e:
            st.exception(e)
    show_table_with_download("kpis", cols, "kpis.csv")

# ----- Risks -----
with tabs[1]:
    st.markdown("Generate **Risk Register** rows linked to tasks.")
    cols = ["element_id","element_name","risk_description","risk_category","likelihood_1to5","impact_1to5","mitigation_owner","control_ref"]
    if st.button("Generate Risks"):
        key = ensure_key()
        prompt = f"""You are a risk analyst.
For these tasks:
{as_tasks_bullets()}

Create a CSV with columns:
{", ".join(cols)}
Return only CSV rows."""
        try:
            csv_text = call_openai_rows(MODEL, key, prompt)
            st.session_state["risks"] = pd.read_csv(io.StringIO(csv_text))
        except Exception as e:
            st.exception(e)
    show_table_with_download("risks", cols, "risks.csv")

# ----- RACI -----
with tabs[2]:
    st.markdown("Generate **RACI** matrix entries per task.")
    cols = ["element_id","element_name","role","responsibility_type"]  # responsibility_type ∈ [R,A,C,I]
    if st.button("Generate RACI"):
        key = ensure_key()
        prompt = f"""You are a process governance expert.
For these tasks:
{as_tasks_bullets()}

Create a CSV with columns:
{", ".join(cols)}
Create 1–3 rows per task. Return only CSV rows."""
        try:
            csv_text = call_openai_rows(MODEL, key, prompt)
            st.session_state["raci"] = pd.read_csv(io.StringIO(csv_text))
        except Exception as e:
            st.exception(e)
    show_table_with_download("raci", cols, "raci.csv")

# ----- Controls -----
with tabs[3]:
    st.markdown("Generate **Controls** mapped to tasks (SOX/ISO/etc.).")
    cols = ["element_id","element_name","control_name","control_type","frequency","evidence_required","owner"]
    if st.button("Generate Controls"):
        key = ensure_key()
        prompt = f"""You are an internal controls specialist.
For these tasks:
{as_tasks_bullets()}

Create a CSV with columns:
{", ".join(cols)}
- control_type: Preventive/Detective/Corrective.
- frequency: per_txn, daily, weekly, monthly.
Return only CSV rows."""
        try:
            csv_text = call_openai_rows(MODEL, key, prompt)
            st.session_state["controls"] = pd.read_csv(io.StringIO(csv_text))
        except Exception as e:
            st.exception(e)
    show_table_with_download("controls", cols, "controls.csv")

# ----- Agents -----
with tabs[4]:
    st.markdown("Generate **AI Agent** capability map per task.")
    cols = ["element_id","element_name","agent_role","capabilities","decision_logic","confidence_threshold","exception_handler","handoff_to"]
    if st.button("Generate Agents"):
        key = ensure_key()
        prompt = f"""You are an AI solution architect.
For these tasks:
{as_tasks_bullets()}

Create a CSV with columns:
{", ".join(cols)}
- confidence_threshold: 0.0–1.0
Return only CSV rows."""
        try:
            csv_text = call_openai_rows(MODEL, key, prompt)
            st.session_state["agents"] = pd.read_csv(io.StringIO(csv_text))
        except Exception as e:
            st.exception(e)
    show_table_with_download("agents", cols, "agents.csv")









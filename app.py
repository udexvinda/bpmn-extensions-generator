import io
import json
import pandas as pd
import streamlit as st
from xml.etree import ElementTree as ET
import re

# ---------- Page ----------
st.set_page_config(page_title="BPMN → Extensions Generator", page_icon="🧩", layout="wide")
st.markdown("""
<style>
.block-container{padding-top:1rem;padding-bottom:1rem}
#canvas{margin-bottom:.5rem;border:1px solid #ddd;border-radius:8px;height:65vh}
.status-card{border:1px solid #E6F4EA;background:#E6F4EA;border-radius:10px;padding:.9rem 1rem;display:flex;gap:.6rem;align-items:center}
.status-card.bad{border-color:#FDE0E0;background:#FDE0E0}
.status-dot{width:10px;height:10px;border-radius:50%;background:#16a34a}
.status-card.bad .status-dot{background:#dc2626}
.status-title{font-weight:600}
</style>
""", unsafe_allow_html=True)

# ---------- Config / Secrets ----------
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", "")
MODEL = st.secrets.get("OPENAI_MODEL", "gpt-4o-mini")

# ---------- API Status (sidebar) ----------
with st.sidebar:
    st.header("API Status")
    if OPENAI_API_KEY:
        st.markdown(
            '<div class="status-card"><div class="status-dot"></div>'
            '<div class="status-title">OpenAI: Connected</div></div>',
            unsafe_allow_html=True,
        )
        st.caption(f"Model: `{MODEL}`")
    else:
        st.markdown(
            '<div class="status-card bad"><div class="status-dot"></div>'
            '<div class="status-title">OpenAI: Not configured</div></div>',
            unsafe_allow_html=True,
        )
        st.caption("Add `OPENAI_API_KEY` in **Secrets** (App → Settings → Secrets) to enable the generators.")

# ---------- Helpers ----------
NS = {"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL"}

def parse_named_tasks(bpmn_xml: str):
    """Find all <bpmn:task ... name="..."> anywhere in the XML."""
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
            tasks.append(r)
            seen.add(r["element_id"])
    return tasks

def clean_csv_text(raw: str) -> str:
    """Strip ``` fences / stray backticks the model might add."""
    txt = (raw or "").strip()
    txt = re.sub(r"^```(?:csv|CSV)?\s*", "", txt)
    txt = re.sub(r"\s*```$", "", txt)
    txt = txt.replace("`", "")
    return txt.strip()

def call_openai_rows(model, api_key, prompt, temperature=0.2):
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    return clean_csv_text(resp.choices[0].message.content)

def df_download_button(df: pd.DataFrame, label: str, filename: str):
    st.download_button(label, df.to_csv(index=False).encode("utf-8"),
                       file_name=filename, mime="text/csv")

def require_key():
    if not OPENAI_API_KEY:
        st.error("OpenAI key is missing. Add `OPENAI_API_KEY` in Secrets to use this feature.")
        st.stop()
    return OPENAI_API_KEY

def show_table_with_download(state_key: str, columns: list, filename: str):
    df = st.session_state.get(state_key)
    if df is None:
        st.dataframe(pd.DataFrame(columns=columns), use_container_width=True)
    else:
        # keep only declared columns if present
        cols = [c for c in columns if c in df.columns]
        st.dataframe(df[cols] if cols else df, use_container_width=True)
        df_download_button(df[cols] if cols else df, f"⬇️ Download {filename}", filename)

def tasks_bullets(tasks):
    return "\n".join(f"- {t['element_name']} (id: {t['element_id']})" for t in tasks) or "- (none)"

# Alignment helpers to force element_id/element_name to match detected tasks
def build_task_maps(tasks):
    id_to_name = {t["element_id"]: t["element_name"] for t in tasks}
    valid_ids = set(id_to_name.keys())
    valid_names = set(id_to_name.values())
    name_to_id = {v: k for k, v in id_to_name.items()}
    return id_to_name, name_to_id, valid_ids, valid_names

def align_to_tasks(df: pd.DataFrame, tasks):
    """Repair AI CSV so element_id / element_name match detected tasks."""
    if not {"element_id", "element_name"}.issubset(df.columns):
        return df
    id_to_name, name_to_id, valid_ids, valid_names = build_task_maps(tasks)

    df = df.copy()
    df["element_id"] = df["element_id"].astype(str).str.strip()
    df["element_name"] = df["element_name"].astype(str).str.strip()

    # Swap if they are reversed
    mask_swap = df["element_id"].isin(valid_names) & df["element_name"].isin(valid_ids)
    df.loc[mask_swap, ["element_id", "element_name"]] = df.loc[mask_swap, ["element_name", "element_id"]].values

    # Move id from name column if needed
    mask_move = ~df["element_id"].isin(valid_ids) & df["element_name"].isin(valid_ids)
    df.loc[mask_move, "element_id"] = df.loc[mask_move, "element_name"]

    # Map from known names to ids where possible
    mask_from_name = ~df["element_id"].isin(valid_ids) & df["element_name"].isin(valid_names)
    df.loc[mask_from_name, "element_id"] = df.loc[mask_from_name, "element_name"].map(name_to_id)

    # Drop rows with unknown ids and set names from id
    df = df[df["element_id"].isin(valid_ids)].copy()
    df["element_name"] = df["element_id"].map(id_to_name)
    return df.reset_index(drop=True)

# ---------- Upload ----------
st.title("BPMN → Extensions Generator")
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
      <bpmndi:BPMNShape id="Start_di" bpmnElement="Start"><dc:Bounds x="100" y="140" width="36" height="36"/></bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Task_A_di" bpmnElement="Task_A"><dc:Bounds x="180" y="120" width="120" height="80"/></bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Task_B_di" bpmnElement="Task_B"><dc:Bounds x="340" y="120" width="120" height="80"/></bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Task_C_di" bpmnElement="Task_C"><dc:Bounds x="500" y="120" width="120" height="80"/></bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="End_di" bpmnElement="End"><dc:Bounds x="660" y="140" width="36" height="36"/></bpmndi:BPMNShape>
      <bpmndi:BPMNEdge id="f1_di" bpmnElement="f1"><di:waypoint x="136" y="158"/><di:waypoint x="180" y="158"/></bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="f2_di" bpmnElement="f2"><di:waypoint x="300" y="160"/><di:waypoint x="340" y="160"/></bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="f3_di" bpmnElement="f3"><di:waypoint x="460" y="160"/><di:waypoint x="500" y="160"/></bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="f4_di" bpmnElement="f4"><di:waypoint x="620" y="158"/><di:waypoint x="660" y="158"/></bpmndi:BPMNEdge>
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

<script src="https://unpkg.com/bpmn-js@10.2.1/dist/bpmn-viewer.production.min.js"></script>
<script src="https://unpkg.com/bpmn-moddle@7.1.3/dist/bpmn-moddle.umd.js"></script>
<script src="https://cdn.jsdelivr.net/npm/bpmn-auto-layout@0.7.0/dist/bpmn-auto-layout.umd.js"></script>
<script src="https://unpkg.com/bpmn-auto-layout@0.7.0/dist/bpmn-auto-layout.umd.js"></script>

<script>
  const xmlIn = {json.dumps(bpmn_xml)};
  const viewer = new BpmnJS({{ container: '#canvas' }});

  const ModdleCtor =
    (window.BpmnModdle && (window.BpmnModdle.BpmnModdle || window.BpmnModdle.default || window.BpmnModdle))
    || null;

  const autoLayoutFn =
    (window.BpmnAutoLayout && (window.BpmnAutoLayout.layout || window.BpmnAutoLayout)) ||
    (window.bpmnAutoLayout && (window.bpmnAutoLayout.layout || window.bpmnAutoLayout)) ||
    null;

  const hasDI = /<\\s*bpmndi:BPMNDiagram[\\s>]/.test(xmlIn);

  (async () => {{
    try {{
      if (hasDI) {{
        await viewer.importXML(xmlIn);
      }} else {{
        if (!ModdleCtor) throw new Error('BpmnModdle UMD not found');
        if (!autoLayoutFn) throw new Error('BpmnAutoLayout UMD not found');

        const moddle = new ModdleCtor();
        const res = await moddle.fromXML(xmlIn);
        const rootElement = res.rootElement;
        const laid = await autoLayoutFn(rootElement);
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
# Persist last results
for _key in ["kpis", "risks", "raci", "controls"]:
    st.session_state.setdefault(_key, None)

tabs = st.tabs(["KPIs", "Risks", "RACI", "Controls"])

# Precompute mapping lines for stricter prompts
mapping_lines = "\n".join(f"{t['element_id']},{t['element_name']}" for t in tasks)

# --- KPIs ---
with tabs[0]:
    st.markdown("Generate **KPI** rows for each task.")
    kpi_cols = ["element_id","element_name","kpi_key","current_value","target_value","owner","last_updated"]
    if st.button("Generate KPIs"):
        key = require_key()
        prompt = f"""You are a BPM KPI designer.

Use exactly these task identifiers and names (do not invent or renumber):
element_id,element_name
{mapping_lines}

Create a CSV with columns (in this exact order):
{", ".join(kpi_cols)}
- Use snake_case for kpi_key.
- current_value/target_value numeric or % where sensible.
- last_updated: YYYY-MM-DD.
Return only clean CSV (no code fences)."""
        try:
            csv_text = call_openai_rows(MODEL, key, prompt)
            df = pd.read_csv(io.StringIO(csv_text))
            df = align_to_tasks(df, tasks)
            st.session_state["kpis"] = df
        except Exception as e:
            st.error(f"CSV parsing failed: {e}")
    show_table_with_download("kpis", kpi_cols, "kpis.csv")

# --- Risks ---
with tabs[1]:
    st.markdown("Generate **Risk Register** rows linked to tasks.")
    risk_cols = ["element_id","element_name","risk_description","risk_category","likelihood_1to5","impact_1to5","mitigation_owner","control_ref"]
    if st.button("Generate Risks"):
        key = require_key()
        prompt = f"""You are a risk analyst.

Use exactly these task identifiers and names (do not invent or renumber):
element_id,element_name
{mapping_lines}

Create a CSV with columns (in this exact order):
{", ".join(risk_cols)}
Ensure comma-separated values and a single header row.
Return pure CSV — no code fences."""
        try:
            csv_text = call_openai_rows(MODEL, key, prompt)
            df = pd.read_csv(io.StringIO(csv_text))
            df = align_to_tasks(df, tasks)
            st.session_state["risks"] = df
        except Exception as e:
            st.error(f"CSV parsing failed: {e}")
    show_table_with_download("risks", risk_cols, "risks.csv")

# --- RACI ---
with tabs[2]:
    st.markdown("Generate **RACI** matrix entries per task.")
    raci_cols = ["element_id","element_name","role","responsibility_type"]
    if st.button("Generate RACI"):
        key = require_key()
        prompt = f"""For the following process tasks use the exact ids and names below.
Do not invent or renumber.

element_id,element_name
{mapping_lines}

Generate a CSV table. Columns (in order): {", ".join(raci_cols)}.
Create 1–3 rows per task, responsibility_type ∈ [R, A, C, I].
Return clean CSV only (no fences)."""
        try:
            csv_text = call_openai_rows(MODEL, key, prompt)
            df = pd.read_csv(io.StringIO(csv_text))
            df = align_to_tasks(df, tasks)
            st.session_state["raci"] = df
        except Exception as e:
            st.error(f"CSV parsing failed: {e}")
    show_table_with_download("raci", raci_cols, "raci.csv")

# --- Controls ---
with tabs[3]:
    st.markdown("Generate **Controls** mapped to tasks (SOX/ISO/etc.).")
    ctrl_cols = ["element_id","element_name","control_name","control_type","frequency","evidence_required","owner"]
    if st.button("Generate Controls"):
        key = require_key()
        prompt = f"""Generate a CSV table for control mappings per task.

Use exactly these task identifiers and names (do not invent or renumber):
element_id,element_name
{mapping_lines}

Columns (in this exact order):
{", ".join(ctrl_cols)}
- control_type: Preventive/Detective/Corrective
- frequency: per_txn, daily, weekly, monthly
Return clean CSV only (no code fences)."""
        try:
            csv_text = call_openai_rows(MODEL, key, prompt)
            df = pd.read_csv(io.StringIO(csv_text))
            df = align_to_tasks(df, tasks)  # <-- ensures element_name matches Detected Tasks
            st.session_state["controls"] = df
        except Exception as e:
            st.error(f"CSV parsing failed: {e}")
    show_table_with_download("controls", ctrl_cols, "controls.csv")
















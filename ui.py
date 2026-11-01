"""Visual theme for the Streamlit app: vibrant multi-colour palette, logo, hero header and section headings."""
import base64
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent
LOGO_SVG = HERE / "logo.svg"
LOGO_PNG = HERE / "logo.png"

# Vibrant categorical palette (used for charts and accents)
PALETTE = ["#7C3AED", "#EC4899", "#F97316", "#FACC15", "#10B981", "#06B6D4", "#3B82F6", "#F43F5E"]
GRADIENT = "linear-gradient(120deg, #7C3AED 0%, #EC4899 35%, #F97316 68%, #FACC15 100%)"


def logo_data_uri():
    try:
        return "data:image/svg+xml;base64," + base64.b64encode(LOGO_SVG.read_bytes()).decode()
    except OSError:
        return ""


def page_icon():
    try:
        from PIL import Image
        return Image.open(LOGO_PNG)
    except Exception:
        return "🛰️"


CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap');
:root {
  --c1:#7C3AED; --c2:#EC4899; --c3:#F97316; --c4:#FACC15; --c5:#10B981; --c6:#06B6D4; --c7:#3B82F6;
  --grad: linear-gradient(120deg,#7C3AED 0%,#EC4899 35%,#F97316 68%,#FACC15 100%);
  --grad-cool: linear-gradient(120deg,#06B6D4 0%,#3B82F6 50%,#7C3AED 100%);
}
html, body, [class*="css"], .stMarkdown, button, input, textarea { font-family: 'Plus Jakarta Sans', system-ui, sans-serif; }

/* soft colourful glow behind the page (translucent, so it works in light and dark themes) */
[data-testid="stAppViewContainer"] {
  background-image:
    radial-gradient(900px 420px at 0% 0%, rgba(124,58,237,.13), transparent 60%),
    radial-gradient(800px 380px at 100% 0%, rgba(236,72,153,.11), transparent 60%),
    radial-gradient(900px 500px at 50% 100%, rgba(6,182,212,.10), transparent 60%);
  background-attachment: fixed;
}
[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 2.2rem; max-width: 1280px; }

/* hero */
.hero { position:relative; overflow:hidden; border-radius:24px; padding:28px 32px; margin-bottom:18px;
  background: var(--grad); color:#fff; box-shadow: 0 18px 50px -18px rgba(124,58,237,.55); display:flex; gap:24px; align-items:center; }
.hero::after { content:""; position:absolute; right:-80px; top:-80px; width:320px; height:320px; border-radius:50%;
  background: radial-gradient(circle, rgba(255,255,255,.28), transparent 65%); }
.hero img { width:96px; height:96px; flex:none; filter: drop-shadow(0 8px 18px rgba(0,0,0,.25)); }
.hero h1 { margin:0; padding:0; font-size:2.05rem; font-weight:800; letter-spacing:-.02em; color:#fff; line-height:1.15; }
.hero p { margin:6px 0 12px; opacity:.95; font-size:1.02rem; color:#fff; }
.chips { display:flex; flex-wrap:wrap; gap:8px; position:relative; z-index:1; }
.chip { background: rgba(255,255,255,.2); border:1px solid rgba(255,255,255,.35); color:#fff; padding:4px 12px;
  border-radius:999px; font-size:.8rem; font-weight:600; backdrop-filter: blur(6px); }
@media (max-width: 640px) { .hero { flex-direction:column; text-align:center; padding:22px 18px; } .chips { justify-content:center; } .hero h1 { font-size:1.55rem; } }

/* section headings */
.sec { display:flex; align-items:center; gap:12px; margin:18px 0 8px; }
.sec .ico { width:38px; height:38px; border-radius:12px; display:grid; place-items:center; font-size:1.15rem; color:#fff; flex:none;
  box-shadow: 0 8px 20px -8px rgba(0,0,0,.35); }
.sec h3 { margin:0; padding:0; font-weight:800; font-size:1.25rem; letter-spacing:-.01em; }
.sec small { display:block; opacity:.7; font-weight:500; font-size:.85rem; }

/* tabs as colourful pills (selectors cover older BaseWeb tabs and newer role-based tabs) */
.stTabs [role="tablist"], .stTabs [data-baseweb="tab-list"] { gap:4px; flex-wrap:wrap; border-bottom:none !important; padding:6px; border-radius:18px;
  background: rgba(127,127,127,.08); box-shadow:none; }
.stTabs [role="tab"], .stTabs [data-baseweb="tab"] { height:auto; padding:8px 11px !important; border-radius:12px; font-weight:700;
  background:transparent; border:none !important; transition: all .2s ease; }
.stTabs [role="tab"] p { font-weight:700; font-size:.88rem; white-space:nowrap; }
.stTabs [role="tab"]:hover { background: rgba(124,58,237,.12); }
.stTabs [role="tab"][aria-selected="true"] { background: var(--grad) !important; color:#fff !important; box-shadow: 0 8px 22px -10px rgba(236,72,153,.8); }
.stTabs [role="tab"][aria-selected="true"] p, .stTabs [role="tab"][aria-selected="true"] * { color:#fff !important; }
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"], .stTabs .react-aria-SelectionIndicator { display:none !important; }
.stTabs [role="tab"]::after, .stTabs [role="tab"]::before { display:none !important; }

/* buttons */
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button {
  background: var(--grad); color:#fff; border:none; border-radius:12px; font-weight:700; padding:.5rem 1.1rem;
  box-shadow: 0 10px 24px -12px rgba(236,72,153,.9); transition: transform .15s ease, box-shadow .15s ease, filter .15s; }
.stButton > button:hover, .stDownloadButton > button:hover { transform: translateY(-1px); filter: saturate(1.15) brightness(1.05); color:#fff;
  box-shadow: 0 14px 28px -12px rgba(124,58,237,.9); }
.stButton > button:focus:not(:active), .stDownloadButton > button:focus:not(:active) { color:#fff; border:none; }
.stDownloadButton > button { background: var(--grad-cool); }

/* metric cards: each gets its own colour */
[data-testid="stMetric"] { border-radius:18px; padding:16px 18px; color:#fff; box-shadow: 0 14px 30px -16px rgba(0,0,0,.45); }
[data-testid="stMetric"] * { color:#fff !important; }
[data-testid="stMetric"] label p { font-weight:600; opacity:.9; }
[data-testid="stMetricValue"] { font-weight:800; }
[data-testid="column"]:nth-of-type(5n+1) [data-testid="stMetric"], [data-testid="stColumn"]:nth-of-type(5n+1) [data-testid="stMetric"] { background: linear-gradient(135deg,#7C3AED,#A855F7); }
[data-testid="column"]:nth-of-type(5n+2) [data-testid="stMetric"], [data-testid="stColumn"]:nth-of-type(5n+2) [data-testid="stMetric"] { background: linear-gradient(135deg,#EC4899,#F43F5E); }
[data-testid="column"]:nth-of-type(5n+3) [data-testid="stMetric"], [data-testid="stColumn"]:nth-of-type(5n+3) [data-testid="stMetric"] { background: linear-gradient(135deg,#F97316,#F59E0B); }
[data-testid="column"]:nth-of-type(5n+4) [data-testid="stMetric"], [data-testid="stColumn"]:nth-of-type(5n+4) [data-testid="stMetric"] { background: linear-gradient(135deg,#10B981,#06B6D4); }
[data-testid="column"]:nth-of-type(5n+5) [data-testid="stMetric"], [data-testid="stColumn"]:nth-of-type(5n+5) [data-testid="stMetric"] { background: linear-gradient(135deg,#3B82F6,#6366F1); }
[data-testid="stMetric"] { background: linear-gradient(135deg,#7C3AED,#EC4899); }

/* dataframes, json, alerts, inputs */
[data-testid="stDataFrame"], [data-testid="stTable"], [data-testid="stJson"] { border-radius:14px; overflow:hidden;
  border:1px solid rgba(124,58,237,.18); box-shadow: 0 8px 24px -18px rgba(124,58,237,.6); }
[data-testid="stAlert"] { border-radius:14px; }
[data-baseweb="select"] > div, [data-baseweb="input"], [data-baseweb="textarea"] { border-radius:12px !important; }
[data-baseweb="tag"] { background: var(--grad) !important; }

/* sidebar */
[data-testid="stSidebar"] { background: linear-gradient(185deg, #1E1B4B 0%, #3B0764 45%, #831843 100%); }
[data-testid="stSidebar"] * { color:#F5F3FF; }
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] { background: rgba(255,255,255,.08); border:1.5px dashed rgba(255,255,255,.4); border-radius:14px; }
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button { background: rgba(255,255,255,.15); color:#fff; border:none; }
[data-testid="stSidebar"] [data-baseweb="input"], [data-testid="stSidebar"] [data-baseweb="input"] > div { background:#FFFFFF !important; }
[data-testid="stSidebar"] input { color:#111827 !important; -webkit-text-fill-color:#111827; }
[data-testid="stSidebar"] [data-testid="stAlert"] { background: rgba(255,255,255,.1); }
[data-testid="stSidebar"] [data-testid="stFileChip"], [data-testid="stSidebar"] [data-testid="stFileUploaderFile"] { background: rgba(255,255,255,.95); border-radius:10px; }
[data-testid="stSidebar"] [data-testid="stFileChip"] *, [data-testid="stSidebar"] [data-testid="stFileUploaderFile"] * { color:#1E1B4B !important; }
[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,.2); }
.side-brand { display:flex; align-items:center; gap:12px; margin-bottom:6px; }
.side-brand img { width:52px; height:52px; }
.side-brand b { font-size:1.2rem; font-weight:800; background: linear-gradient(90deg,#F0ABFC,#FDBA74,#FDE047); -webkit-background-clip:text; background-clip:text; color:transparent !important; }
.side-brand span { display:block; font-size:.75rem; opacity:.8; }
.stat-row { display:flex; gap:8px; margin:6px 0 2px; }
.stat { flex:1; background: rgba(255,255,255,.1); border-radius:12px; padding:8px 10px; text-align:center; }
.stat b { display:block; font-size:1.25rem; }
.stat small { font-size:.7rem; opacity:.8; }

/* chat */
[data-testid="stChatMessage"] { border-radius:16px; border:1px solid rgba(124,58,237,.15); }
[data-testid="stChatInput"] { border-radius:16px; }

/* practical cards on the guide tab */
.pcard { border-radius:18px; padding:18px 20px; color:#fff; background: var(--grad-cool); box-shadow: 0 16px 36px -18px rgba(59,130,246,.8); }
.pcard .n { font-size:.8rem; font-weight:700; opacity:.85; letter-spacing:.08em; text-transform:uppercase; }
.pcard h4 { margin:.2rem 0 .6rem; color:#fff; font-weight:800; }
.pcard p { margin:.2rem 0; color:#fff; }
.flow { display:flex; flex-wrap:wrap; gap:6px; margin:10px 0 4px; }
.flow span { padding:6px 12px; border-radius:999px; font-size:.8rem; font-weight:700; color:#fff; }
.foot { text-align:center; opacity:.65; font-size:.8rem; margin-top:28px; }
</style>
"""

SECTION_COLOURS = {
    "violet": "linear-gradient(135deg,#7C3AED,#A855F7)", "pink": "linear-gradient(135deg,#EC4899,#F43F5E)",
    "orange": "linear-gradient(135deg,#F97316,#F59E0B)", "green": "linear-gradient(135deg,#10B981,#06B6D4)",
    "blue": "linear-gradient(135deg,#3B82F6,#6366F1)",
}


def apply_theme():
    st.markdown(CSS, unsafe_allow_html=True)


def hero(version):
    chips = ["MOLUSCE geometry QA", "Area & transitions", "Accuracy & kappa", "Hindcast FoM", "NSE · PBIAS · KGE", "AI agent"]
    st.markdown(f"""
<div class="hero">
  <img src="{logo_data_uri()}" alt="LULC Agent logo"/>
  <div style="position:relative;z-index:1">
    <h1>LULC · MOLUSCE · SWAT+ Agent</h1>
    <p>Audited land-cover change, simulation validation and hydrology checks, with an AI agent that uses the same tools. v{version}</p>
    <div class="chips">{''.join(f'<span class="chip">{c}</span>' for c in chips)}</div>
  </div>
</div>""", unsafe_allow_html=True)


def section(icon, title, subtitle="", colour="violet"):
    sub = f"<small>{subtitle}</small>" if subtitle else ""
    st.markdown(f'<div class="sec"><div class="ico" style="background:{SECTION_COLOURS[colour]}">{icon}</div>'
                f'<div><h3>{title}</h3>{sub}</div></div>', unsafe_allow_html=True)


def sidebar_brand(version, n_rasters, n_tables, n_outputs):
    st.markdown(f"""
<div class="side-brand"><img src="{logo_data_uri()}" alt=""/><div><b>LULC Agent</b><span>v{version} · experimental research tool</span></div></div>
<div class="stat-row">
  <div class="stat"><b>{n_rasters}</b><small>rasters</small></div>
  <div class="stat"><b>{n_tables}</b><small>tables</small></div>
  <div class="stat"><b>{n_outputs}</b><small>outputs</small></div>
</div>""", unsafe_allow_html=True)


def workflow_strip():
    steps = ["Imagery", "Classification", "Accuracy", "Change", "MOLUSCE", "Hindcast", "SWAT+", "Scenarios", "Thesis"]
    st.markdown('<div class="flow">' + "".join(
        f'<span style="background:{PALETTE[i % len(PALETTE)]}">{i + 1}. {s}</span>' for i, s in enumerate(steps)) + "</div>",
        unsafe_allow_html=True)


def practical_card(n, title, deliverable, viva):
    st.markdown(f'<div class="pcard"><div class="n">Practical {n} of 30</div><h4>{title}</h4>'
                f'<p><b>Deliverable:</b> {deliverable}</p><p><b>Viva question:</b> {viva}</p></div>', unsafe_allow_html=True)


def bar_chart(df, x, y, title=None):
    """Bar chart in the app palette (one colour per category)."""
    import altair as alt
    cats = df[x].astype(str).tolist()
    chart = (alt.Chart(df.assign(**{x: df[x].astype(str)}))
             .mark_bar(cornerRadiusTopLeft=8, cornerRadiusTopRight=8)
             .encode(x=alt.X(f"{x}:N", sort=cats, title=None, axis=alt.Axis(labelAngle=0)),
                     y=alt.Y(f"{y}:Q", title=title or y),
                     color=alt.Color(f"{x}:N", sort=cats, legend=None,
                                     scale=alt.Scale(domain=cats, range=[PALETTE[i % len(PALETTE)] for i in range(len(cats))])),
                     tooltip=[x, alt.Tooltip(f"{y}:Q", format=",.2f")])
             .properties(height=320))
    st.altair_chart(chart)


def footer():
    st.markdown('<div class="foot">Research software · verify every number independently before it enters a thesis · MIT licence</div>',
                unsafe_allow_html=True)

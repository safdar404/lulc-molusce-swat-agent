"""Visual theme for the Streamlit app: vibrant multi-colour palette, logo, hero header and section headings."""
import base64
import html
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent
LOGO_SVG = HERE / "logo.svg"
LOGO_PNG = HERE / "logo.png"
LOGO_SMALL = HERE / "logo_small.png"  # pre-rendered: cheap to draw, unlike the filtered SVG
GLOBE_TEXTURE = HERE / "globe_texture.png"  # dot-matrix land, equirectangular, from Natural Earth 110 m land (public domain)

# Vibrant categorical palette (used for charts and accents)
PALETTE = ["#7C3AED", "#EC4899", "#F97316", "#FACC15", "#10B981", "#06B6D4", "#3B82F6", "#F43F5E"]
GRADIENT = "linear-gradient(120deg, #7C3AED 0%, #EC4899 35%, #F97316 68%, #FACC15 100%)"


@st.cache_data(show_spinner=False)
def logo_data_uri():
    for path, mime in ((LOGO_SMALL, "image/png"), (LOGO_SVG, "image/svg+xml")):
        try:
            return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()
        except OSError:
            continue
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
  border-radius:999px; font-size:.8rem; font-weight:600; }
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
/* ===================== 3D layer ===================== */

/* hero: raised slab with an edge, glossy top, perspective grid floor and floating 3D logo */
.hero { transform-style: preserve-3d; transform: perspective(1400px) rotateX(3deg); transform-origin: 50% 100%;
  box-shadow: 0 2px 0 rgba(255,255,255,.35) inset, 0 -6px 18px rgba(0,0,0,.12) inset,
              0 10px 0 #6D28D9, 0 12px 0 #5B21B6, 0 34px 60px -18px rgba(91,33,182,.75);
  margin-bottom: 30px; transition: transform .5s cubic-bezier(.2,.8,.2,1); }
.hero:hover { transform: perspective(1400px) rotateX(0deg) translateY(-2px); }
.hero::before { content:""; position:absolute; left:-10%; right:-10%; bottom:-40%; height:90%; pointer-events:none;
  background-image: linear-gradient(rgba(255,255,255,.22) 1.5px, transparent 1.5px), linear-gradient(90deg, rgba(255,255,255,.22) 1.5px, transparent 1.5px);
  background-size: 44px 44px; transform: perspective(380px) rotateX(62deg); transform-origin: 50% 100%;
  -webkit-mask-image: linear-gradient(to top, #000 10%, transparent 85%); mask-image: linear-gradient(to top, #000 10%, transparent 85%); }
.hero img { width:112px; height:112px; filter: drop-shadow(0 14px 12px rgba(30,27,75,.4));
  transform: rotate(-4deg); transition: transform .5s cubic-bezier(.2,.8,.2,1); }
.hero:hover img { transform: translateY(-8px) rotate(4deg) scale(1.04); }
.hero h1 { text-shadow: 0 1px 0 #DB2777, 0 2px 0 #BE185D, 0 3px 0 #9D174D, 0 4px 0 #831843, 0 10px 18px rgba(0,0,0,.35); }
.chip { box-shadow: 0 3px 0 rgba(0,0,0,.18), inset 0 1px 0 rgba(255,255,255,.45); transition: transform .2s; }
.chip:hover { transform: translateY(-2px); }

/* section icon tiles: little 3D blocks */
.sec .ico { box-shadow: inset 0 2px 0 rgba(255,255,255,.45), inset 0 -3px 0 rgba(0,0,0,.18), 0 4px 0 rgba(0,0,0,.22), 0 12px 18px -8px rgba(0,0,0,.45);
  transform: perspective(300px) rotateX(10deg) rotateY(-10deg); }

/* tabs: recessed tray with raised pills */
.stTabs [role="tablist"], .stTabs [data-baseweb="tab-list"] {
  box-shadow: inset 0 3px 8px rgba(30,27,75,.16), inset 0 -1px 0 rgba(255,255,255,.6) !important; }
.stTabs [role="tab"][aria-selected="true"] { transform: translateY(-2px);
  box-shadow: inset 0 2px 0 rgba(255,255,255,.4), 0 4px 0 #9D174D, 0 12px 20px -8px rgba(236,72,153,.85) !important; }

/* buttons: extruded keys that press down */
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button {
  box-shadow: inset 0 2px 0 rgba(255,255,255,.4), 0 5px 0 #6D28D9, 0 14px 22px -10px rgba(109,40,217,.8);
  transform: translateY(0); }
.stButton > button:hover, .stDownloadButton > button:hover {
  transform: translateY(-2px); box-shadow: inset 0 2px 0 rgba(255,255,255,.4), 0 7px 0 #6D28D9, 0 18px 26px -10px rgba(109,40,217,.85); }
.stButton > button:active, .stDownloadButton > button:active {
  transform: translateY(4px); box-shadow: inset 0 2px 0 rgba(255,255,255,.3), 0 1px 0 #6D28D9, 0 4px 10px -4px rgba(109,40,217,.7); }
.stDownloadButton > button { box-shadow: inset 0 2px 0 rgba(255,255,255,.4), 0 5px 0 #1D4ED8, 0 14px 22px -10px rgba(29,78,216,.8); }

/* metric cards: glossy 3D tiles with a coloured edge that tilt on hover */
[data-testid="stMetric"] { position:relative; overflow:hidden; transform: perspective(700px) rotateX(6deg); transform-origin: 50% 100%;
  transition: transform .35s cubic-bezier(.2,.8,.2,1), box-shadow .35s; margin-bottom: 10px; }
[data-testid="stMetric"]::before { content:""; position:absolute; inset:0 0 50% 0; pointer-events:none;
  background: linear-gradient(180deg, rgba(255,255,255,.32), rgba(255,255,255,0)); }
[data-testid="stMetric"]::after { content:""; position:absolute; width:120px; height:120px; right:-30px; bottom:-50px; border-radius:50%;
  background: rgba(255,255,255,.14); pointer-events:none; }
[data-testid="stMetric"]:hover { transform: perspective(700px) rotateX(0deg) rotateY(-6deg) translateY(-6px); }
[data-testid="column"]:nth-of-type(5n+1) [data-testid="stMetric"], [data-testid="stColumn"]:nth-of-type(5n+1) [data-testid="stMetric"] { box-shadow: inset 0 2px 0 rgba(255,255,255,.4), 0 8px 0 #5B21B6, 0 24px 30px -14px rgba(91,33,182,.8); }
[data-testid="column"]:nth-of-type(5n+2) [data-testid="stMetric"], [data-testid="stColumn"]:nth-of-type(5n+2) [data-testid="stMetric"] { box-shadow: inset 0 2px 0 rgba(255,255,255,.4), 0 8px 0 #BE185D, 0 24px 30px -14px rgba(190,24,93,.8); }
[data-testid="column"]:nth-of-type(5n+3) [data-testid="stMetric"], [data-testid="stColumn"]:nth-of-type(5n+3) [data-testid="stMetric"] { box-shadow: inset 0 2px 0 rgba(255,255,255,.4), 0 8px 0 #C2410C, 0 24px 30px -14px rgba(194,65,12,.8); }
[data-testid="column"]:nth-of-type(5n+4) [data-testid="stMetric"], [data-testid="stColumn"]:nth-of-type(5n+4) [data-testid="stMetric"] { box-shadow: inset 0 2px 0 rgba(255,255,255,.4), 0 8px 0 #047857, 0 24px 30px -14px rgba(4,120,87,.8); }
[data-testid="column"]:nth-of-type(5n+5) [data-testid="stMetric"], [data-testid="stColumn"]:nth-of-type(5n+5) [data-testid="stMetric"] { box-shadow: inset 0 2px 0 rgba(255,255,255,.4), 0 8px 0 #1D4ED8, 0 24px 30px -14px rgba(29,78,216,.8); }
[data-testid="stMetricValue"] { text-shadow: 0 2px 0 rgba(0,0,0,.18), 0 6px 12px rgba(0,0,0,.2); }

/* practical card + workflow chips: floating 3D */
.pcard { position:relative; overflow:hidden; transform: perspective(1000px) rotateX(4deg); transform-origin: 50% 100%;
  box-shadow: inset 0 2px 0 rgba(255,255,255,.4), 0 8px 0 #4338CA, 0 30px 40px -18px rgba(67,56,202,.8); transition: transform .4s; margin-bottom: 12px; }
.pcard:hover { transform: perspective(1000px) rotateX(0deg) translateY(-3px); }
.pcard::before { content:""; position:absolute; inset:0 0 55% 0; background: linear-gradient(180deg, rgba(255,255,255,.25), transparent); pointer-events:none; }
.flow span { box-shadow: inset 0 1px 0 rgba(255,255,255,.45), 0 4px 0 rgba(0,0,0,.25), 0 8px 12px -6px rgba(0,0,0,.4); transition: transform .2s; }
.flow span:hover { transform: translateY(-3px) rotateX(10deg); }

/* data panels: lifted sheets */
[data-testid="stDataFrame"], [data-testid="stTable"], [data-testid="stJson"], [data-testid="stVegaLiteChart"], [data-testid="stArrowVegaLiteChart"] {
  border-radius:16px; box-shadow: 0 1px 0 rgba(255,255,255,.7) inset, 0 6px 0 rgba(124,58,237,.12), 0 22px 36px -22px rgba(76,29,149,.55); }
[data-baseweb="select"] > div, [data-baseweb="input"] { box-shadow: inset 0 2px 5px rgba(30,27,75,.10); }

/* sidebar: glass tiles with depth */
.side-brand img { filter: drop-shadow(0 6px 8px rgba(0,0,0,.45)); transition: transform .4s; }
.side-brand:hover img { transform: translateY(-4px) rotate(-6deg); }
.stat { box-shadow: inset 0 1px 0 rgba(255,255,255,.25), 0 4px 0 rgba(0,0,0,.25), 0 10px 18px -8px rgba(0,0,0,.6);
  background: linear-gradient(180deg, rgba(255,255,255,.18), rgba(255,255,255,.06)); }
.stat b { text-shadow: 0 2px 0 rgba(0,0,0,.3); }
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] { box-shadow: inset 0 4px 10px rgba(0,0,0,.25); }
[data-testid="stSidebar"] [data-testid="stFileChip"] { box-shadow: 0 3px 0 rgba(0,0,0,.25); }
[data-testid="stChatMessage"] { box-shadow: 0 4px 0 rgba(124,58,237,.10), 0 14px 24px -16px rgba(76,29,149,.5); }

/* ===================== spinning globe, AI-vision HUD (v1.4.8) ===================== */
.globe-wrap { --d:150px; position:relative; flex:none; width:calc(var(--d) + 44px); height:calc(var(--d) + 44px); display:grid; place-items:center; z-index:1; }
.globe { position:relative; width:var(--d); height:var(--d); border-radius:50%; overflow:hidden;
  background: radial-gradient(circle at 35% 30%, #1E3A8A 0%, #172554 55%, #0B1030 100%);
  box-shadow: 0 0 0 2px rgba(255,255,255,.35), 0 0 30px 6px rgba(103,232,249,.45), 0 18px 30px -8px rgba(30,27,75,.6); }
.globe-map { position:absolute; inset:0; background-repeat:repeat-x; background-size: calc(var(--d) * 2) var(--d);
  animation: globe-spin 24s linear infinite; filter: drop-shadow(0 0 2px rgba(103,232,249,.9)); }
@keyframes globe-spin { from { background-position: 0 0; } to { background-position: calc(var(--d) * 2) 0; } }
.globe-grid { position:absolute; inset:0; border-radius:50%; opacity:.35;
  background: repeating-linear-gradient(0deg, transparent 0 18px, rgba(165,243,252,.55) 18px 19px),
              radial-gradient(ellipse 18% 50% at 50% 50%, transparent 97%, rgba(165,243,252,.6) 98%, transparent 100%),
              radial-gradient(ellipse 36% 50% at 50% 50%, transparent 98%, rgba(165,243,252,.6) 99%, transparent 100%); }
.globe-scan { position:absolute; left:0; right:0; height:34%; top:-34%;
  background: linear-gradient(180deg, transparent, rgba(103,232,249,.10) 60%, rgba(103,232,249,.55) 98%, #A5F3FC 100%);
  animation: globe-scan 3.6s cubic-bezier(.45,0,.55,1) infinite; }
@keyframes globe-scan { 0% { top:-34%; } 100% { top:100%; } }
.globe-shade { position:absolute; inset:0; border-radius:50%; pointer-events:none;
  background: radial-gradient(circle at 32% 28%, rgba(255,255,255,.38), transparent 38%),
              radial-gradient(circle at 70% 75%, rgba(0,0,0,.55), transparent 60%); box-shadow: inset -14px -10px 30px rgba(0,0,0,.55); }
.ping { position:absolute; width:8px; height:8px; margin:-4px; border-radius:50%; background:#FDE047; box-shadow:0 0 8px #FDE047;
  animation: ping 3.3s ease-out infinite; }
@keyframes ping { 0% { box-shadow:0 0 0 0 rgba(253,224,71,.85); opacity:1; } 70% { box-shadow:0 0 0 14px rgba(253,224,71,0); } 100% { opacity:.4; } }
.orbit { position:absolute; inset:6px; border-radius:50%; border:1.5px dashed rgba(255,255,255,.45); animation: orbit 14s linear infinite; }
.orbit.o2 { inset:14px 0; border-style:solid; border-color: rgba(253,224,71,.35); transform: rotate(-24deg); animation-duration: 9s; animation-direction: reverse; }
.orbit i { position:absolute; top:-5px; left:50%; width:10px; height:10px; margin-left:-5px; border-radius:3px; background:#fff;
  box-shadow: 0 0 10px #fff, -7px 0 0 -2px #A5F3FC, 7px 0 0 -2px #A5F3FC; }
.orbit.o2 i { background:#FDE047; box-shadow:0 0 10px #FDE047; border-radius:50%; width:7px; height:7px; }
@keyframes orbit { from { rotate:0deg; } to { rotate:360deg; } }
.bracket { position:absolute; inset:0; pointer-events:none;
  background: linear-gradient(#fff,#fff) top left/18px 2px, linear-gradient(#fff,#fff) top left/2px 18px,
              linear-gradient(#fff,#fff) top right/18px 2px, linear-gradient(#fff,#fff) top right/2px 18px,
              linear-gradient(#fff,#fff) bottom left/18px 2px, linear-gradient(#fff,#fff) bottom left/2px 18px,
              linear-gradient(#fff,#fff) bottom right/18px 2px, linear-gradient(#fff,#fff) bottom right/2px 18px;
  background-repeat:no-repeat; opacity:.85; animation: lock 3.6s ease-in-out infinite; }
@keyframes lock { 0%,100% { inset:0; opacity:.85; } 50% { inset:8px; opacity:.5; } }
.hud { position:absolute; font: 700 .62rem/1 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing:.12em; color:#fff;
  text-shadow: 0 1px 2px rgba(0,0,0,.5); text-transform:uppercase; white-space:nowrap; }
.hud-tl { top:-4px; left:22px; } .hud-br { bottom:-4px; right:22px; } .hud-br b { color:#F43F5E; animation: blink 1.2s steps(2) infinite; }
.hud-bl { bottom:-20px; left:50%; transform:translateX(-50%); text-transform:none; letter-spacing:.04em; opacity:.95; }
.cls { position:relative; display:inline-block; width:5.2em; height:1em; vertical-align:bottom; }
.cls em { position:absolute; left:0; font-style:normal; color:#FDE047; opacity:0; animation: cls 12s infinite; }
@keyframes cls { 0% { opacity:0; transform:translateY(4px); } 3%,14% { opacity:1; transform:none; } 17%,100% { opacity:0; } }
@keyframes blink { 50% { opacity:0; } }
.hero { flex-wrap:wrap; justify-content:center; }
.hero > .hero-text { flex:1 1 340px; min-width:0; }
.tele { display:flex; flex-wrap:wrap; gap:6px; margin:0 0 12px; position:relative; z-index:1; }
.tele span { font: 700 .78rem/1.1 ui-monospace, SFMono-Regular, Menlo, monospace; color:#fff; padding:5px 10px; border-radius:8px;
  background: rgba(15,23,42,.38); border:1px solid rgba(165,243,252,.45); box-shadow: inset 0 0 12px rgba(103,232,249,.18); }
.tele small { display:block; font-size:.6rem; letter-spacing:.12em; text-transform:uppercase; opacity:.75; margin-bottom:2px; }
@media (max-width: 640px) { .globe-wrap { --d:120px; margin-bottom:14px; } .tele { justify-content:center; } }

/* layers & files table of contents (sidebar) */
.toc-h { display:flex; align-items:center; gap:6px; font-weight:800; font-size:.78rem; letter-spacing:.04em; margin:10px 0 4px; opacity:.95; }
.toc-h span { margin-left:auto; background: rgba(255,255,255,.18); border-radius:999px; padding:0 8px; font-size:.7rem; }
ul.toc { list-style:none; margin:0; padding:0; }
ul.toc li { display:flex; align-items:center; gap:8px; margin:0 0 5px; padding:6px 8px; border-radius:10px;
  background: linear-gradient(180deg, rgba(255,255,255,.14), rgba(255,255,255,.05)); box-shadow: inset 0 1px 0 rgba(255,255,255,.18); }
ul.toc li > div { min-width:0; flex:1; }
ul.toc b { display:block; font-size:.8rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
ul.toc small { display:block; font-size:.66rem; opacity:.78; line-height:1.3; }
.toc .dot { width:8px; height:8px; border-radius:50%; flex:none; background:#A5F3FC; box-shadow:0 0 6px currentColor; }
.toc .dot.output { background:#FDE047; } .toc .dot.vector { background:#86EFAC; } .toc .dot.table { background:#F9A8D4; }
.toc .dot.running { background:#FDBA74; animation: blink 1s steps(2) infinite; } .toc .dot.failed { background:#F43F5E; }
.toc .tag { font-style:normal; font-size:.58rem; font-weight:800; text-transform:uppercase; letter-spacing:.06em; padding:2px 6px; border-radius:6px;
  background: rgba(255,255,255,.16); flex:none; }
.toc-empty { font-size:.8rem; opacity:.8; }
[data-testid="stSidebar"] [data-testid="stExpander"] details { background: rgba(255,255,255,.07); border:1px solid rgba(255,255,255,.28) !important;
  border-radius:14px; box-shadow: inset 0 1px 0 rgba(255,255,255,.2), 0 10px 18px -10px rgba(0,0,0,.6); }
[data-testid="stSidebar"] [data-testid="stExpander"] summary { background: transparent !important; border-radius:14px; }
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover { background: rgba(255,255,255,.08) !important; }
[data-testid="stSidebar"] [data-testid="stExpander"] summary p { font-weight:800; color:#fff !important; }

@media (prefers-reduced-motion: reduce) {
  .globe-map, .globe-scan, .ping, .orbit, .bracket, .cls em, .hud-br b, .toc .dot.running { animation: none !important; }
  .cls em:first-child { opacity:1; }
  .hero img, .side-brand img, .hero:hover img, .side-brand:hover img { transition: none; transform: none; }
  .hero, .hero:hover, [data-testid="stMetric"], [data-testid="stMetric"]:hover, .pcard, .pcard:hover { transition: none; }
}
@media (max-width: 640px) { .hero { transform: none; } }
</style>
"""

SECTION_COLOURS = {
    "violet": "linear-gradient(135deg,#7C3AED,#A855F7)", "pink": "linear-gradient(135deg,#EC4899,#F43F5E)",
    "orange": "linear-gradient(135deg,#F97316,#F59E0B)", "green": "linear-gradient(135deg,#10B981,#06B6D4)",
    "blue": "linear-gradient(135deg,#3B82F6,#6366F1)",
}


def apply_theme():
    st.markdown(CSS, unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def globe_texture_uri():
    try:
        return "data:image/png;base64," + base64.b64encode(GLOBE_TEXTURE.read_bytes()).decode()
    except OSError:
        return ""


def globe_html():
    """Spinning dot-matrix Earth seen through an 'AI vision' HUD: scan beam, detection brackets, orbiting satellites, class read-out.
    Pure CSS (Streamlit markdown cannot run scripts); motion stops for users who ask for reduced motion."""
    classes = ["forest", "snow / ice", "water", "built-up", "cropland", "bare soil"]
    return f"""
<div class="globe-wrap" aria-hidden="true">
  <div class="orbit o1"><i></i></div><div class="orbit o2"><i></i></div>
  <div class="globe">
    <div class="globe-map" style="background-image:url('{globe_texture_uri()}')"></div>
    <div class="globe-grid"></div><div class="globe-scan"></div>
    <span class="ping" style="left:38%;top:34%"></span><span class="ping" style="left:62%;top:46%;animation-delay:1.1s"></span>
    <span class="ping" style="left:47%;top:66%;animation-delay:2.2s"></span>
    <div class="globe-shade"></div>
  </div>
  <div class="bracket"></div>
  <div class="hud hud-tl">AI&nbsp;VISION</div><div class="hud hud-br"><b>●</b> REC</div>
  <div class="hud hud-bl">classifying&nbsp;<span class="cls">{''.join(f'<em style="animation-delay:{i * 2}s">{c}</em>' for i, c in enumerate(classes))}</span></div>
</div>"""


def hero(version, status=None):
    """status: optional live read-outs [(label, value), ...] shown as an AI telemetry strip."""
    chips = ["RF / SVM classification", "Olofsson accuracy", "Intensity analysis", "Landscape metrics", "Gi* hotspots",
             "Markov-CA scenarios", "Hindcast FoM", "SWAT+ · CN · RUSLE", "AI agent"]
    tele = ""
    if status:
        tele = '<div class="tele">' + "".join(f'<span><small>{html.escape(str(k))}</small>{html.escape(str(v))}</span>' for k, v in status) + "</div>"
    st.markdown(f"""
<div class="hero">
  {globe_html()}
  <div class="hero-text" style="position:relative;z-index:1">
    <h1>LULC · MOLUSCE · SWAT+ Agent</h1>
    <p>Classify, validate, explain, simulate and link land-cover change to SWAT+ hydrology, with an AI agent that uses the same audited tools. v{version}</p>
    {tele}
    <div class="chips">{''.join(f'<span class="chip">{c}</span>' for c in chips)}</div>
  </div>
</div>""", unsafe_allow_html=True)


def _mb(n_bytes):
    return f"{n_bytes / 1e6:.1f} MB" if n_bytes >= 1e5 else f"{n_bytes / 1e3:.0f} kB"


def toc_items(ctx, job=None):
    """Plain data for the layers / files table of contents, grouped like a GIS layer panel. Kept free of Streamlit for testing."""
    groups = []
    store, outs = ctx.store, ctx.store.outputs
    rows = []
    for name, r in store.rasters.items():
        h, w = r.data.shape
        nb = 1 if r.bands is None else r.bands.shape[0]
        crs = r.crs
        epsg = crs.to_epsg() if crs else None
        unit = "m" if crs is not None and crs.is_projected else "°"
        px = f"{abs(r.transform.a):.3g} {unit}" if r.transform is not None else "?"
        valid = 100.0 * (1 - r.mask.mean()) if r.mask.size else 0.0
        rows.append(dict(name=name, tag="output" if name in outs else "upload",
                         detail=f"{w}×{h} px · {nb} band{'s' if nb > 1 else ''} · {px} · {('EPSG:' + str(epsg)) if epsg else (crs.to_string()[:18] if crs else 'no CRS')} · {valid:.0f}% valid"))
    groups.append(("🗺️", "Raster layers", rows))
    groups.append(("💾", "Generated outputs (not loaded as layers)",
                   [dict(name=n, tag="output", detail=_mb(len(b))) for n, b in outs.items() if n not in store.rasters]))
    vrows = []
    for name, g in (getattr(ctx, "vectors", None) or {}).items():
        try:
            gt = ", ".join(sorted(set(g.geom_type.dropna().astype(str))))[:30] or "empty"
            epsg = g.crs.to_epsg() if g.crs is not None else None
            vrows.append(dict(name=name, tag="vector", detail=f"{len(g)} feature{'s' if len(g) != 1 else ''} · {gt} · {('EPSG:' + str(epsg)) if epsg else 'no CRS'}"))
        except Exception:  # noqa: BLE001 - a TOC must never break the page
            vrows.append(dict(name=name, tag="vector", detail="(unreadable)"))
    groups.append(("🧭", "Vector layers", vrows))
    groups.append(("📊", "Tables", [dict(name=n, tag="table", detail=f"{len(df)} rows × {df.shape[1]} cols") for n, df in ctx.tables.items()]))
    jrows = []
    if job is not None:
        if getattr(job, "running", False):
            jrows.append(dict(name=getattr(job, "name", "job"), tag="running", detail=f"{100 * job.progress:.0f}% · {job.message}"[:90]))
        elif getattr(job, "error", None):
            jrows.append(dict(name=getattr(job, "name", "job"), tag="failed", detail=str(job.error)[:90]))
    groups.append(("⏳", "Background jobs", jrows))
    return groups


def layers_toc(ctx, job=None):
    groups = toc_items(ctx, job)
    total = sum(len(rows) for _, _, rows in groups[:4])
    with st.expander(f"🗂️ Layers & files ({total})", expanded=True):
        if not any(rows for _, _, rows in groups):
            st.markdown('<div class="toc-empty">Nothing loaded yet. Upload rasters, vectors or tables below, or download imagery in 🌍.</div>',
                        unsafe_allow_html=True)
            return
        out = []
        for ico, title, rows in groups:
            if not rows:
                continue
            out.append(f'<div class="toc-h">{ico} {title} <span>{len(rows)}</span></div><ul class="toc">')
            for r in rows:
                out.append(f'<li><i class="dot {r["tag"]}"></i><div><b title="{html.escape(r["name"])}">{html.escape(r["name"])}</b>'
                           f'<small>{html.escape(r["detail"])}</small></div><em class="tag {r["tag"]}">{r["tag"]}</em></li>')
            out.append("</ul>")
        st.markdown("".join(out), unsafe_allow_html=True)


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

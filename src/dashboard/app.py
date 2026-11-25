"""AeroPulse — airspace intelligence dashboard (Streamlit)."""
from __future__ import annotations

import base64
import html
import inspect as _inspect
import io
import json
import math
import os
import re
from datetime import datetime, timezone

import pandas as pd
import pydeck as pdk
import requests
import streamlit as st
import streamlit.components.v1 as components
from streamlit.errors import StreamlitAPIException

API_URL = os.getenv("API_URL", "http://api:8000")
CACHE_TTL = 20
MAP_STYLE = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"

st.set_page_config(
    page_title="AeroPulse · Airspace Intelligence",
    layout="wide",
    initial_sidebar_state="expanded",
)

for k, v in {
    "similarity_open": False,
    "selected_hex": None,
    "trigger_similar": False,
    "similar_result": None,
    "row_explanations": {},
    "expanded_rows": set(),
    "expanded_matches": set(),
    "table_page": 1,
    "payload_sig": None,
    "map_view": None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ---------- Styles ----------
st.markdown(
    """
    <style>
    html { color-scheme: dark !important; }
    :root {
        --ap-bg:        #070b12;
        --ap-panel:     #0f1419;
        --ap-panel-hi:  #161c24;
        --ap-inset:     #0b1017;
        --ap-border:    #1e2630;
        --ap-border-hi: #2a3543;
        --ap-fg:        #e6edf3;
        --ap-fg-2:      #b8c2cc;
        --ap-fg-3:      #8b949e;
        --ap-fg-4:      #5c6670;
        --ap-cyan:      #22d3ee;
        --ap-amber:     #fbbf24;
        --ap-red:       #f87171;
        --ap-green:     #4ade80;
        --ap-mono: "SF Mono", "JetBrains Mono", Menlo, Consolas, "Liberation Mono", monospace;
    }

    /* ---- Base ---- */
    body, .stApp, [data-testid="stAppViewContainer"] {
        background-color: var(--ap-bg) !important;
        color: var(--ap-fg) !important;
    }
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                     "Helvetica Neue", Arial, sans-serif;
        -webkit-font-smoothing: antialiased;
    }
    .stMarkdown, .stMarkdown p, .stMarkdown span, .stText,
    [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] span,
    [data-testid="stMarkdownContainer"] div,
    [data-testid="stText"] { color: var(--ap-fg) !important; }
    label, [data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] * {
        color: var(--ap-fg-2) !important;
    }
    [data-testid="stCaptionContainer"], .stCaption { color: var(--ap-fg-3) !important; }
    code, .ap-mono { font-family: var(--ap-mono); }
    .block-container { padding-top: 1.5rem; padding-bottom: 3rem; max-width: 1560px; }

    /* ---- No dimming/flash while a fragment or the page reruns ---- */
    [data-stale="true"], [data-stale="true"] * { opacity: 1 !important; transition: none !important; }
    [data-testid="stStatusWidget"] { display: none !important; }

    /* ---- Hide Streamlit chrome ---- */
    #MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"],
    [data-testid="stDeployButton"] { display: none !important; visibility: hidden !important; }
    [data-testid="stHeader"] { background: transparent !important; height: 0 !important; }

    /* ---- Sidebar = similarity side tab ---- */
    section[data-testid="stSidebar"] {
        background: var(--ap-panel) !important;
        border-right: 1px solid var(--ap-border-hi);
        width: 440px !important;
        min-width: 440px !important;
        box-shadow: 8px 0 32px rgba(0, 0, 0, 0.35);
    }
    section[data-testid="stSidebar"] > div { background: var(--ap-panel) !important; }
    [data-testid="stSidebarHeader"],
    [data-testid="stSidebarCollapseButton"],
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="collapsedControl"] { display: none !important; }
    [data-testid="stSidebarUserContent"] { padding: 1.25rem 1.25rem 2rem 1.25rem !important; }
    @media (max-width: 900px) {
        section[data-testid="stSidebar"] { width: 100% !important; min-width: 0 !important; }
    }

    /* ---- Brand / header ---- */
    .ap-eyebrow {
        font-size: 0.66rem; font-weight: 700; letter-spacing: 0.18em;
        text-transform: uppercase; color: var(--ap-cyan) !important; margin: 0;
    }
    .ap-h1 {
        font-family: var(--ap-mono); font-size: 1.4rem; font-weight: 600;
        letter-spacing: 0.1em; color: var(--ap-fg) !important;
        margin: 0.1rem 0 0 0; line-height: 1.1; text-transform: uppercase;
    }
    .ap-status { display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap; padding-top: 0.55rem; }
    .ap-clock {
        font-family: var(--ap-mono); font-size: 0.82rem; letter-spacing: 0.04em;
        color: var(--ap-fg-2) !important; font-variant-numeric: tabular-nums;
    }

    /* ---- Labels, titles, rules ---- */
    .ap-label {
        font-size: 0.68rem; font-weight: 700; letter-spacing: 0.16em;
        text-transform: uppercase; color: var(--ap-fg-3) !important;
        margin: 0.9rem 0 0.4rem 0; display: block;
    }
    .ap-rule { border: none; border-top: 1px solid var(--ap-border); margin: 1.75rem 0; }
    .ap-section-title {
        font-size: 0.72rem; font-weight: 700; letter-spacing: 0.18em;
        text-transform: uppercase; color: var(--ap-cyan) !important;
        margin: 0 0 0.85rem 0; padding-bottom: 0.5rem;
        border-bottom: 1px solid var(--ap-border);
    }

    /* ---- Telemetry cards ---- */
    .ap-kpi-grid {
        display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 0.75rem;
    }
    .ap-kpi-card {
        position: relative; overflow: hidden; border-radius: 8px;
        background: linear-gradient(180deg, var(--ap-panel-hi), var(--ap-panel));
        border: 1px solid var(--ap-border); padding: 0.95rem 1.1rem 0.9rem 1.25rem;
    }
    .ap-kpi-card::before {
        content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
        background: var(--accent, var(--ap-border-hi));
    }
    .ap-kpi-label {
        font-size: 0.64rem; font-weight: 700; letter-spacing: 0.16em; text-transform: uppercase;
        color: var(--ap-fg-3) !important; margin: 0 0 0.55rem 0;
    }
    .ap-kpi-value {
        font-family: var(--ap-mono); font-size: 2rem; font-weight: 600; letter-spacing: -0.03em;
        line-height: 1; color: var(--ap-fg) !important; font-variant-numeric: tabular-nums; margin: 0 0 0.8rem 0;
    }
    .ap-kpi-meter {
        display: flex; height: 4px; border-radius: 2px; overflow: hidden;
        background: var(--ap-border); margin-bottom: 0.5rem;
    }
    .ap-kpi-meter > span { display: block; height: 100%; }
    .ap-kpi-sub {
        font-family: var(--ap-mono); font-size: 0.68rem; letter-spacing: 0.04em;
        color: var(--ap-fg-3) !important; margin: 0;
    }

    /* ---- Brief ---- */
    .ap-brief {
        border-left: 2px solid var(--ap-cyan); padding: 0.2rem 0 0.2rem 1.1rem;
        font-size: 0.94rem; line-height: 1.75; color: var(--ap-fg-2) !important;
        white-space: pre-line;
        overflow-wrap: anywhere;
        word-break: break-word;
        max-width: 100%;
        min-width: 0;
        box-sizing: border-box;
    }

    /* ---- Pills / badges ---- */
    .ap-pill {
        display: inline-flex; align-items: center; gap: 0.45rem;
        padding: 0.22rem 0.6rem; border-radius: 999px;
        font-family: var(--ap-mono); font-size: 0.68rem; font-weight: 500;
        letter-spacing: 0.06em; background: var(--ap-panel);
        color: var(--ap-fg-2) !important; border: 1px solid var(--ap-border-hi);
        text-transform: uppercase;
    }
    .ap-pill-dot {
        width: 6px; height: 6px; border-radius: 50%; background: var(--ap-green);
        box-shadow: 0 0 6px rgba(74, 222, 128, 0.8);
    }
    .ap-pill-dot-warn { background: var(--ap-amber); box-shadow: 0 0 6px rgba(251,191,36,0.7); }
    .ap-pill-dot-err  { background: var(--ap-red);   box-shadow: 0 0 6px rgba(248,113,113,0.7); }
    .ap-badge {
        display: inline-block; padding: 2px 8px; border-radius: 3px;
        font-size: 0.68rem; font-weight: 700; letter-spacing: 0.05em;
        text-transform: uppercase; white-space: nowrap; border: 1px solid transparent;
        color: var(--ap-fg-2);
    }
    .ap-badge-descent { background: rgba(251,191,36,0.12); color: var(--ap-amber) !important; border-color: rgba(251,191,36,0.35); }
    .ap-badge-hold    { background: rgba(34,211,238,0.10); color: var(--ap-cyan) !important;  border-color: rgba(34,211,238,0.35); }

    /* ---- Alerts ---- */
    .ap-alert {
        border: 1px solid rgba(248,113,113,0.4); background: rgba(248,113,113,0.08);
        border-radius: 6px; padding: 0.85rem 1.1rem; margin: 0 0 1.25rem 0;
        font-size: 0.86rem; color: var(--ap-fg-2) !important;
    }
    .ap-alert b { color: var(--ap-red) !important; letter-spacing: 0.06em; }
    .ap-empty {
        border: 1px dashed var(--ap-border-hi); border-radius: 6px;
        padding: 1.5rem; text-align: center; color: var(--ap-fg-3) !important; font-size: 0.86rem;
    }

    /* ---- Buttons ---- */
    div[data-testid="stButton"] > button {
        min-height: 2.1rem; padding: 0.28rem 0.75rem; font-size: 0.78rem; font-weight: 500;
        font-family: inherit; border-radius: 6px; background: var(--ap-panel-hi);
        color: var(--ap-fg) !important; border: 1px solid var(--ap-border-hi);
        transition: all 0.12s ease;
    }
    div[data-testid="stButton"] > button,
    div[data-testid="stButton"] > button * {
        white-space: nowrap !important; word-break: keep-all !important;
    }
    div[data-testid="stButton"] > button { padding-left: 0.5rem; padding-right: 0.5rem; }
    div[data-testid="stButton"] > button:hover { background: #1e2732; border-color: #3a4757; }
    div[data-testid="stButton"] > button:disabled { opacity: 0.4; }
    div[data-testid="stButton"] > button[kind="primary"] {
        background: rgba(34,211,238,0.12); color: var(--ap-cyan) !important;
        border-color: rgba(34,211,238,0.4);
    }
    div[data-testid="stButton"] > button[kind="primary"]:hover { background: rgba(34,211,238,0.22); }

    /* ---- Inputs ---- */
    .stTextInput input[type="text"], .stTextInput > div > div > input {
        background-color: var(--ap-panel) !important; border: 1px solid var(--ap-border) !important;
        color: var(--ap-fg) !important; font-size: 0.85rem; border-radius: 6px;
    }
    .stTextInput input::placeholder { color: var(--ap-fg-4) !important; }
    .stTextInput input:focus { border-color: var(--ap-cyan) !important; outline: none; }
    div[data-baseweb="select"] > div {
        background-color: var(--ap-panel-hi) !important; border-color: var(--ap-border) !important;
        color: var(--ap-fg) !important; border-radius: 6px;
    }
    div[data-baseweb="popover"] ul, div[data-baseweb="popover"] li {
        background-color: var(--ap-panel) !important; color: var(--ap-fg) !important;
    }
    div[data-baseweb="popover"] li:hover { background-color: var(--ap-panel-hi) !important; }
    div[data-baseweb="tag"] { background-color: rgba(34,211,238,0.15) !important; color: var(--ap-cyan) !important; }
    [data-testid="stSlider"] [role="slider"] { background-color: var(--ap-cyan) !important; }
    [data-testid="stTickBarMin"], [data-testid="stTickBarMax"] { color: var(--ap-fg-3) !important; }

    /* ---- Map ---- */
    .ap-legend { display: flex; gap: 1.75rem; padding: 0.4rem 0 0.9rem 0; align-items: center; flex-wrap: wrap; }
    .ap-legend-item {
        display: inline-flex; align-items: center; gap: 0.5rem; font-size: 0.74rem;
        font-weight: 600; letter-spacing: 0.06em; color: var(--ap-fg-2) !important; text-transform: uppercase;
    }
    .ap-legend-note { margin-left: auto; font-size: 0.7rem; color: var(--ap-fg-4) !important; }
    [data-testid="stDeckGlJsonChart"] {
        border: 1px solid var(--ap-border); border-radius: 6px; overflow: hidden;
    }

    /* ---- Side tab: header, target card, matches ---- */
    .ap-side-head { border-bottom: 1px solid var(--ap-border); padding-bottom: 0.9rem; margin-bottom: 0.4rem; }
    .ap-side-title {
        font-family: var(--ap-mono); font-size: 0.8rem; font-weight: 700;
        letter-spacing: 0.18em; text-transform: uppercase; color: var(--ap-cyan) !important; margin: 0;
    }
    .ap-side-sub { font-size: 0.78rem; color: var(--ap-fg-3) !important; margin: 0.3rem 0 0 0; line-height: 1.5; }
    .ap-target {
        background: var(--ap-inset); border: 1px solid var(--ap-border);
        border-left: 2px solid var(--ap-cyan); border-radius: 6px; padding: 1rem 1.1rem;
    }
    .ap-target-head { display: flex; justify-content: space-between; align-items: center; gap: 0.75rem; }
    .ap-target-id { display: flex; align-items: center; gap: 0.75rem; }
    .ap-target-hex {
        font-family: var(--ap-mono); font-size: 1.1rem; font-weight: 600;
        color: var(--ap-fg) !important; letter-spacing: 0.03em; margin: 0;
    }
    .ap-target-callsign {
        font-family: var(--ap-mono); font-size: 0.8rem; color: var(--ap-cyan) !important;
        letter-spacing: 0.04em; margin: 0.1rem 0 0 0;
    }
    .ap-telemetry {
        display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1px;
        background: var(--ap-border); border: 1px solid var(--ap-border);
        border-radius: 6px; margin: 0.9rem 0; overflow: hidden;
    }
    .ap-tel-cell { background: var(--ap-inset); padding: 0.55rem 0.8rem; }
    .ap-tel-label {
        font-size: 0.58rem; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase;
        color: var(--ap-fg-4) !important; margin: 0 0 0.2rem 0;
    }
    .ap-tel-value {
        font-family: var(--ap-mono); font-size: 0.88rem; font-weight: 500;
        color: var(--ap-fg) !important; margin: 0; font-variant-numeric: tabular-nums;
    }
    .ap-target-explanation { font-size: 0.85rem; line-height: 1.65; color: var(--ap-fg-2) !important; margin: 0; }
    .ap-match {
        background: var(--ap-inset); border: 1px solid var(--ap-border);
        border-radius: 6px; padding: 0.8rem 0.95rem; margin-bottom: 0.6rem;
    }
    .ap-match-head { display: flex; justify-content: space-between; align-items: center; gap: 0.75rem; margin-bottom: 0.5rem; }
    .ap-match-rank { font-family: var(--ap-mono); font-size: 0.7rem; font-weight: 700; color: var(--ap-fg-4) !important; }
    .ap-match-id { flex: 1; font-family: var(--ap-mono); font-size: 0.8rem; color: var(--ap-fg) !important; }
    .ap-match-id span { color: var(--ap-cyan) !important; }
    .ap-match-score { font-family: var(--ap-mono); font-size: 0.74rem; color: var(--ap-cyan) !important; }
    .ap-bar { height: 3px; background: var(--ap-border); border-radius: 2px; overflow: hidden; margin-bottom: 0.5rem; }
    .ap-bar-fill {
        height: 100%; background: linear-gradient(90deg, rgba(34,211,238,0.5), var(--ap-cyan));
        box-shadow: 0 0 8px rgba(34,211,238,0.5);
    }
    .ap-match-text {
        font-size: 0.82rem; line-height: 1.65; color: var(--ap-fg-2) !important;
        white-space: pre-line; overflow-wrap: anywhere;
    }
    .ap-target-explanation { white-space: pre-line; overflow-wrap: anywhere; }
    .ap-detail { margin-top: 1rem; }

    div[data-testid="stDownloadButton"] > button {
        min-height: 2.1rem; padding: 0.28rem 0.6rem; font-size: 0.78rem; font-weight: 500;
        border-radius: 6px; background: var(--ap-panel-hi); color: var(--ap-fg) !important;
        border: 1px solid var(--ap-border-hi); white-space: nowrap !important;
    }
    div[data-testid="stDownloadButton"] > button * { white-space: nowrap !important; }
    div[data-testid="stDownloadButton"] > button:hover { background: #1e2732; border-color: #3a4757; }

    /* ---- Roster rows ---- */
    [class*="st-key-rowd_"], [class*="st-key-rowh_"] {
        background: var(--ap-panel);
        border: 1px solid var(--ap-border);
        border-left: 3px solid var(--row-accent, var(--ap-border-hi));
        border-radius: 10px;
        padding: 1.15rem 1.4rem 1.2rem 1.4rem;
        margin-bottom: 1rem;
        overflow: hidden;
        transition: border-color 0.12s ease, background 0.12s ease;
    }
    [class*="st-key-rowd_"] { --row-accent: var(--ap-amber); }
    [class*="st-key-rowh_"] { --row-accent: var(--ap-cyan); }
    [class*="st-key-rowd_"]:hover, [class*="st-key-rowh_"]:hover {
        background: var(--ap-panel-hi);
    }

    /* Header line inside the row */
    .ap-row-head {
        display: flex; align-items: center; gap: 0.9rem; flex-wrap: wrap;
        min-width: 0;
    }
    .ap-row-id-text { display: flex; flex-direction: column; gap: 0.15rem; min-width: 0; }
    .ap-row-call {
        font-family: var(--ap-mono); font-size: 1.05rem; font-weight: 600;
        color: var(--ap-fg) !important; letter-spacing: 0.03em; margin: 0; line-height: 1.2;
    }
    .ap-hex {
        font-family: var(--ap-mono); font-size: 0.76rem; color: var(--ap-cyan) !important;
        letter-spacing: 0.03em;
    }

    /* Full-width metrics grid below the header */
    .ap-row-metrics {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
        gap: 0.85rem 1.6rem;
        margin-top: 0.9rem;
        padding-top: 0.9rem;
        border-top: 1px dashed var(--ap-border);
    }
    .ap-m { min-width: 0; }
    .ap-m-l {
        display: block; font-size: 0.62rem; font-weight: 700; letter-spacing: 0.14em;
        text-transform: uppercase; color: var(--ap-fg-4) !important; margin-bottom: 0.3rem;
    }
    .ap-m-v {
        display: block; font-family: var(--ap-mono); font-size: 0.88rem;
        color: var(--ap-fg) !important; font-variant-numeric: tabular-nums;
        overflow-wrap: anywhere; word-break: break-word;
    }

    /* Observation line */
    .ap-row-obs {
        margin-top: 0.85rem;
        padding-top: 0.85rem;
        border-top: 1px dashed var(--ap-border);
        font-size: 0.83rem;
        line-height: 1.65;
        color: var(--ap-fg-2) !important;
        overflow-wrap: anywhere;
        word-break: break-word;
    }
    .ap-row-obs b {
        font-family: var(--ap-mono); font-size: 0.62rem; font-weight: 700;
        letter-spacing: 0.14em; text-transform: uppercase;
        color: var(--ap-fg-4) !important; margin-right: 0.7rem;
    }

    /* Explanation box (expanded) */
    .ap-expl {
        margin-top: 1rem;
        padding: 0.95rem 1.15rem;
        background: var(--ap-inset);
        border: 1px solid var(--ap-border);
        border-left: 2px solid var(--ap-green);
        border-radius: 6px;
        font-size: 0.86rem;
        line-height: 1.7;
        color: var(--ap-fg-2) !important;
        white-space: pre-line;
        overflow-wrap: anywhere;
        word-break: break-word;
        box-sizing: border-box;
    }
    .ap-expl-label {
        display: block;
        font-family: var(--ap-mono); font-size: 0.64rem; font-weight: 700;
        letter-spacing: 0.14em; text-transform: uppercase;
        color: var(--ap-green) !important;
        margin: 0 0 0.55rem 0;
    }

    .ap-roster-head { display: flex; align-items: baseline; gap: 0.6rem; margin: 0.25rem 0 0.7rem 0; }
    .ap-roster-count { font-family: var(--ap-mono); font-size: 0.78rem; color: var(--ap-fg-3) !important; }
    .ap-footer { font-size: 0.66rem; letter-spacing: 0.14em; text-transform: uppercase; color: var(--ap-fg-4) !important; }

    @media (max-width: 640px) {
        .block-container { padding-left: 1rem; padding-right: 1rem; }
        [class*="st-key-rowd_"], [class*="st-key-rowh_"] { padding: 1rem; }
        [class*="st-key-rowd_"] [data-testid="stHorizontalBlock"],
        [class*="st-key-rowh_"] [data-testid="stHorizontalBlock"] {
            flex-wrap: wrap !important; gap: 0.5rem !important;
        }
        [class*="st-key-rowd_"] [data-testid="stColumn"]:first-child,
        [class*="st-key-rowh_"] [data-testid="stColumn"]:first-child {
            flex: 1 1 100% !important; min-width: 100% !important;
        }
        [class*="st-key-rowd_"] [data-testid="stColumn"]:nth-child(n+2),
        [class*="st-key-rowh_"] [data-testid="stColumn"]:nth-child(n+2) {
            flex: 1 1 calc(50% - 0.25rem) !important;
            min-width: calc(50% - 0.25rem) !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------- Constants ----------
TYPE_LABELS = {
    "rapid_descent": "Rapid descent",
    "holding_pattern": "Holding pattern",
}
TYPE_COLORS = {
    "rapid_descent": [251, 191, 36, 255],
    "holding_pattern": [34, 211, 238, 255],
}
VISIBLE_TYPES = set(TYPE_LABELS.keys())
HEADING_KEYS = ("track", "true_track", "heading", "hdg", "trk", "track_deg", "true_heading")
ICON_PX = 64
_ST_VER = tuple(int(p) for p in re.findall(r"\d+", st.__version__)[:2])

LIVE_CLOCK_HTML = """
<script>
(function () {
  let doc;
  try { doc = window.parent.document; } catch (e) { doc = document; }
  const pad = (n) => String(n).padStart(2, "0");
  function tick() {
    const d = new Date();
    const dateStr = d.getUTCFullYear() + "-" + pad(d.getUTCMonth() + 1) + "-" + pad(d.getUTCDate());
    const timeStr = pad(d.getUTCHours()) + ":" + pad(d.getUTCMinutes()) + ":" + pad(d.getUTCSeconds());
    const t = dateStr + " " + timeStr + " UTC";
    ["ap-clock", "ap-clock-foot"].forEach(function (id) {
      const el = doc.getElementById(id);
      if (el) el.textContent = t;
    });
  }
  tick();
  if (window.__apClockTimer) clearInterval(window.__apClockTimer);
  window.__apClockTimer = setInterval(tick, 1000);
})();
</script>
"""

_FULL = (
    {"width": "stretch"}
    if "width" in _inspect.signature(st.button).parameters
    else {"use_container_width": True}
)


# ---------- Formatting helpers ----------
def _esc(x) -> str:
    return html.escape("" if x is None else str(x))


def _txt(x) -> str:
    if x is None:
        return ""
    try:
        if pd.isna(x):
            return ""
    except (TypeError, ValueError):
        pass
    return str(x)


def _color(t: str) -> list[int]:
    return TYPE_COLORS.get(t, [160, 160, 160, 255])


def _badge(t: str) -> str:
    if t == "rapid_descent":
        return "<span class='ap-badge ap-badge-descent'>Rapid descent</span>"
    if t == "holding_pattern":
        return "<span class='ap-badge ap-badge-hold'>Holding pattern</span>"
    return f"<span class='ap-badge'>{_esc(t)}</span>"


def _fmt_coords(lat, lon) -> str:
    if pd.isna(lat) or pd.isna(lon):
        return "—"
    return f"{abs(lat):.3f}° {'N' if lat >= 0 else 'S'}, {abs(lon):.3f}° {'E' if lon >= 0 else 'W'}"


def _fmt_lat(lat) -> str:
    return "—" if lat is None or pd.isna(lat) else f"{abs(lat):.3f}° {'N' if lat >= 0 else 'S'}"


def _fmt_lon(lon) -> str:
    return "—" if lon is None or pd.isna(lon) else f"{abs(lon):.3f}° {'E' if lon >= 0 else 'W'}"


def _fmt_utc(ms) -> str:
    if ms is None or isinstance(ms, bool):
        return "—"
    try:
        if pd.isna(ms):
            return "—"
    except (TypeError, ValueError):
        pass

    if isinstance(ms, str):
        s = ms.strip()
        if not s:
            return "—"
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt.strftime("%a %Y-%m-%d %H:%M:%S UTC")
        except ValueError:
            pass

    try:
        num = float(ms)
        if not math.isfinite(num) or num <= 0:
            return "—"
        sec = num if num < 1e11 else num / 1000.0
        dt = datetime.fromtimestamp(sec, tz=timezone.utc)
        return dt.strftime("%a %Y-%m-%d %H:%M:%S UTC")
    except (ValueError, TypeError, OSError):
        return "—"


def _fmt_alt(alt) -> str:
    return f"{alt:,.0f} ft" if pd.notna(alt) else "—"


def _fmt_hdg(h) -> str:
    return "—" if h is None or pd.isna(h) else f"{h % 360:03.0f}°"


def _tel(label: str, value: str) -> str:
    return f'<div class="ap-tel-cell"><p class="ap-tel-label">{label}</p><p class="ap-tel-value">{value}</p></div>'
# ---------- Match helpers ----------

def _match_coords(m: dict, fallback_an: dict | None = None) -> tuple[float | None, float | None]:
    src = fallback_an or {}
    lat = m.get("lat") if m.get("lat") is not None else src.get("lat")
    lon = m.get("lon") if m.get("lon") is not None else src.get("lon")
    try:
        lat_f = float(lat) if lat is not None and not pd.isna(lat) else None
    except (TypeError, ValueError):
        lat_f = None
    try:
        lon_f = float(lon) if lon is not None and not pd.isna(lon) else None
    except (TypeError, ValueError):
        lon_f = None
    return lat_f, lon_f


def _toggle_match_expand(match_key: str, hex_code: str | None) -> None:
    if match_key in st.session_state.expanded_matches:
        st.session_state.expanded_matches.remove(match_key)
        return
    st.session_state.expanded_matches.add(match_key)
    if hex_code and hex_code != "—":
        _get_explanation(hex_code)
# ---------- Airplane geometry & icons ----------
def _plane_points() -> list[tuple[float, float]]:
    right = [
        (54, 9), (55.5, 34), (97, 60), (97, 67), (55.5, 57),
        (54.5, 80), (72, 91), (72, 96.5), (52, 93.5),
    ]
    left = [(100 - x, y) for x, y in reversed(right)]
    return [(50, 2)] + right + [(50, 97)] + left


def _plane_svg(rgb, heading: float = 0.0, size: int = 22) -> str:
    pts = " ".join(f"{x},{y}" for x, y in _plane_points())
    r, g, b = rgb[0], rgb[1], rgb[2]
    return (
        f"<svg width='{size}' height='{size}' viewBox='0 0 100 100' "
        f"style='transform:rotate({heading}deg);flex:none;'>"
        f"<polygon points='{pts}' fill='rgb({r},{g},{b})' stroke='#070b12' "
        f"stroke-width='3' stroke-linejoin='round'/></svg>"
    )


@st.cache_resource(show_spinner=False)
def _plane_icon(rgb: tuple[int, int, int]) -> dict:
    from PIL import Image, ImageDraw

    ss = 4
    big = ICON_PX * ss
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pts = [(x * big / 100, y * big / 100) for x, y in _plane_points()]
    d.polygon(pts, fill=(*rgb, 255))
    d.line(pts + [pts[0]], fill=(7, 11, 18, 255), width=int(2.4 * ss), joint="curve")
    img = img.resize((ICON_PX, ICON_PX), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    return {"url": uri, "width": ICON_PX, "height": ICON_PX, "anchorY": ICON_PX // 2}


def _swatch(rgba: list[int]) -> str:
    return _plane_svg(rgba, 0, 18)


# ---------- Heading logic ----------
def _reported_heading(a: dict):
    for k in HEADING_KEYS:
        v = a.get(k)
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            return f % 360
    return None


def _bearing(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _resolve_headings(df_all: pd.DataFrame) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for hx, g in df_all.groupby("hex", sort=False):
        rep = g["hdg_rep"].iloc[0]
        if pd.notna(rep):
            out[hx] = float(rep)
            continue
        pos = g.dropna(subset=["lat", "lon"])
        out[hx] = None
        if len(pos) < 2:
            continue
        lat0, lon0 = float(pos["lat"].iloc[0]), float(pos["lon"].iloc[0])
        for _, older in pos.iloc[1:13].iterrows():
            dlat = lat0 - older["lat"]
            dlon = (lon0 - older["lon"]) * math.cos(math.radians(lat0))
            if math.hypot(dlat, dlon) > 0.003:
                out[hx] = _bearing(float(older["lat"]), float(older["lon"]), lat0, lon0)
                break
    return out


# ---------- API ----------
def _fetch(path: str, params: dict | None = None):
    try:
        r = requests.get(f"{API_URL}{path}", params=params or {}, timeout=8)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def api_get(path: str, params: dict | None = None):
    return _fetch(path, params)


def _payload_sig(stats, anomalies, brief=None) -> tuple:
    s = stats if isinstance(stats, dict) else {}
    a = anomalies if isinstance(anomalies, list) else []
    b = brief if isinstance(brief, dict) else {}
    latest = max((x.get("detected_at_ms") or 0 for x in a), default=0)
    brief_sig = (b.get("generated_at"), b.get("provider"), b.get("text"))
    return (s.get("total_anomalies"), s.get("window_minutes"), latest, len(a), brief_sig)


def _rerun_app() -> None:
    try:
        st.rerun(scope="app")
    except (StreamlitAPIException, TypeError):
        st.rerun()


@st.fragment(run_every=CACHE_TTL)
def _poll_for_updates() -> None:
    brief = _fetch("/airspace/brief")
    stats = _fetch("/stats", {"window_minutes": 60})
    anomalies = _fetch("/anomalies", {"since_minutes": 60, "limit": 500})
    sig = _payload_sig(stats, anomalies, brief)
    if sig == st.session_state.payload_sig:
        return
    st.session_state.payload_sig = sig
    st.cache_data.clear()
    _rerun_app()


# ---------- Session helpers ----------
def _match_detected_ms(m: dict, fallback_an: dict | None = None) -> int | None:
    for k in ("detected_at_ms", "ts", "last_seen_ms", "timestamp"):
        v = m.get(k)
        if v is not None and not isinstance(v, bool):
            try:
                num = float(v)
                if math.isfinite(num):
                    return int(num * 1000) if 0 < num < 1e11 else int(num)
            except (TypeError, ValueError):
                continue
    if fallback_an:
        v = fallback_an.get("detected_at_ms")
        if v is not None:
            try:
                return int(float(v))
            except (TypeError, ValueError):
                pass
    return None


def _blended_similarity_score(base_score: float, target_ms: int | None, match_ms: int | None) -> float:
    base = max(0.0, min(1.0, float(base_score)))
    if target_ms is None or match_ms is None or target_ms <= 0 or match_ms <= 0:
        return base
    # Decay over a 60-minute window (3,600,000 ms) so closer detection times rank higher
    delta_ms = abs(target_ms - match_ms)
    time_score = math.exp(-delta_ms / 3_600_000.0)
    return 0.85 * base + 0.15 * time_score


def _open_similarity(hex_code: str | None = None) -> None:
    st.session_state.similarity_open = True
    st.session_state.similar_result = None
    if hex_code:
        st.session_state.selected_hex = hex_code
        st.session_state.console_pick = hex_code
        st.session_state.trigger_similar = True


def _close_similarity() -> None:
    st.session_state.similarity_open = False
    st.session_state.similar_result = None


def _toggle_similarity() -> None:
    if st.session_state.similarity_open:
        _close_similarity()
    else:
        _open_similarity()


def _get_explanation(hex_code: str) -> tuple[str, str]:
    if hex_code in _expl_by_hex:
        return ("ok", _expl_by_hex[hex_code])
    if hex_code not in st.session_state.row_explanations:
        res = api_get("/similar", {"hex_": hex_code, "limit": 1})
        if res and isinstance(res, dict) and res.get("query_explanation"):
            st.session_state.row_explanations[hex_code] = ("ok", res["query_explanation"])
        else:
            st.session_state.row_explanations[hex_code] = (
                "missing",
                "No AI explanation has been generated for this aircraft yet.",
            )
    return st.session_state.row_explanations[hex_code]


def _toggle_explain(hex_code: str) -> None:
    if hex_code in st.session_state.expanded_rows:
        st.session_state.expanded_rows.remove(hex_code)
        return
    st.session_state.expanded_rows.add(hex_code)
    _get_explanation(hex_code)


def _download(label: str, data, file_name: str, mime: str, key: str) -> None:
    kw = {"on_click": "ignore"} if _ST_VER >= (1, 43) else {}
    st.download_button(label, data=data, file_name=file_name, mime=mime, key=key, **_FULL, **kw)


def _rerun_fragment() -> None:
    try:
        st.rerun(scope="fragment")
    except (StreamlitAPIException, TypeError):
        st.rerun()


def _row_container(key: str):
    try:
        return st.container(key=key)
    except TypeError:
        return st.container()


def _num(x):
    return None if x is None or pd.isna(x) else float(x)


def _clear_filters() -> None:
    for _k in ("q_input", "type_filter", "alt_filter", "sort_by"):
        st.session_state.pop(_k, None)
    st.session_state.table_page = 1


def _roster_csv(d: pd.DataFrame) -> bytes:
    out = pd.DataFrame({
        "icao": d["hex"],
        "callsign": d["flight"],
        "anomaly": d["type"].map(TYPE_LABELS).fillna(d["type"]),
        "observation": d["details"],
        "altitude_ft": d["alt"],
        "heading_deg": d["hex"].map(_headings).round(0),
        "latitude": d["lat"],
        "longitude": d["lon"],
        "last_seen_utc": pd.to_datetime(d["ts"], unit="ms", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    return out.to_csv(index=False).encode("utf-8")


def _roster_geojson(d: pd.DataFrame) -> bytes:
    feats = []
    for r in d.dropna(subset=["lat", "lon"]).itertuples():
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(r.lon), float(r.lat)]},
            "properties": {
                "icao": r.hex, "callsign": r.flight or None,
                "anomaly": TYPE_LABELS.get(r.type, r.type),
                "observation": _txt(getattr(r, "details", "")),
                "altitude_ft": _num(r.alt), "heading_deg": _num(_headings.get(r.hex)),
                "last_seen_ms": int(r.ts),
            },
        })
    return json.dumps({"type": "FeatureCollection", "features": feats}).encode("utf-8")


# ---------- Fetch ----------
_brief = api_get("/airspace/brief")
_stats = api_get("/stats", {"window_minutes": 60})
_raw_an = api_get("/anomalies", {"since_minutes": 60, "limit": 500})
_an = _raw_an if isinstance(_raw_an, list) else []
_an = [a for a in _an if a.get("anomaly_type") in VISIBLE_TYPES]

_expl_by_hex: dict[str, str] = {}
for _a in sorted(_an, key=lambda r: r.get("detected_at_ms") or 0, reverse=True):
    if _a.get("explanation") and _a["hex"] not in _expl_by_hex:
        _expl_by_hex[_a["hex"]] = _a["explanation"]
_api_down = _brief is None and _stats is None and _raw_an is None

_COLS = ["hex", "flight", "type", "alt", "lat", "lon", "ts", "hdg_rep", "details", "provider"]
if _an:
    df_all = pd.DataFrame(
        [
            {
                "hex": a["hex"],
                "flight": a.get("flight") or "",
                "type": a["anomaly_type"],
                "alt": a.get("alt_baro_ft"),
                "lat": a.get("lat"),
                "lon": a.get("lon"),
                "ts": a["detected_at_ms"],
                "hdg_rep": _reported_heading(a),
                "details": a.get("details") or "",
                "provider": a.get("explanation_provider") or "",
            }
            for a in _an
        ]
    ).sort_values("ts", ascending=False)
else:
    df_all = pd.DataFrame(columns=_COLS)

_headings = _resolve_headings(df_all) if not df_all.empty else {}
_det_counts = df_all["hex"].value_counts().to_dict() if not df_all.empty else {}

if st.session_state.payload_sig is None:
    st.session_state.payload_sig = _payload_sig(_stats, _raw_an, _brief)
_poll_for_updates()


# ---------- Header ----------
now = datetime.now(timezone.utc)
h1, h2, h3 = st.columns([5, 2, 1.2])

with h1:
    st.markdown(
        """
        <div>
            <p class="ap-eyebrow">Airspace intelligence</p>
            <p class="ap-h1">AeroPulse</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    _status = f'<div class="ap-status"><span class="ap-clock" id="ap-clock">{now.strftime("%Y-%m-%d %H:%M:%S")} UTC</span>'
    if isinstance(_brief, dict) and _brief.get("generated_at"):
        try:
            ts = datetime.fromisoformat(_brief["generated_at"].replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_s = (now - ts).total_seconds()
            if age_s < 1800:
                dot_cls, lbl = "ap-pill-dot", f"Live · {int(age_s // 60)}m"
            elif age_s < 7200:
                dot_cls, lbl = "ap-pill-dot ap-pill-dot-warn", f"Stale · {int(age_s // 60)}m"
            else:
                dot_cls, lbl = "ap-pill-dot ap-pill-dot-err", f"Stale · {age_s / 3600:.1f}h"
            _status += f'<span class="ap-pill"><span class="{dot_cls}"></span>{lbl}</span>'
        except (ValueError, TypeError):
            pass
    _status += "</div>"
    st.markdown(_status, unsafe_allow_html=True)

with h2:
    st.markdown("<div style='height:0.6rem;'></div>", unsafe_allow_html=True)
    st.button(
        "Close similarity" if st.session_state.similarity_open else "Similarity",
        type="primary",
        **_FULL,
        on_click=_toggle_similarity,
        key="toggle_similarity",
    )
with h3:
    st.markdown("<div style='height:0.6rem;'></div>", unsafe_allow_html=True)
    if st.button("Refresh", **_FULL):
        st.cache_data.clear()
        st.session_state.row_explanations.clear()
        st.session_state.payload_sig = None
        st.rerun()

components.html(LIVE_CLOCK_HTML, height=1, scrolling=False)

st.markdown('<hr class="ap-rule" style="margin:1.25rem 0 1.5rem 0;">', unsafe_allow_html=True)

if _api_down:
    st.markdown(
        '<div class="ap-alert"><b>DATA SERVICE UNREACHABLE</b><br/>'
        f"The dashboard could not reach <span class='ap-mono'>{_esc(API_URL)}</span>. "
        "Showing no data. Use Refresh to retry.</div>",
        unsafe_allow_html=True,
    )


# ---------- Similarity side tab ----------
@st.fragment
def _render_similarity_tab() -> None:
    st.markdown(
        '<div class="ap-side-head"><p class="ap-side-title">Kinematic &amp; profile similarity</p>'
        '<p class="ap-side-sub">Compare flight regime and kinematics across aircraft, '
        "and inspect prior occurrences for the selected hex.</p></div>",
        unsafe_allow_html=True,
    )
    if st.button("Close panel", **_FULL, key="close_console"):
        _close_similarity()
        st.rerun()

    if not _an:
        st.markdown('<div class="ap-empty">No anomalies in the current window.</div>', unsafe_allow_html=True)
        return

    _labels: dict[str, str] = {}
    for a in _an:
        if a["hex"] not in _labels:
            _labels[a["hex"]] = f"{a['flight']} · {a['hex']}" if a.get("flight") else a["hex"]
    _opts = list(_labels.keys())

    if st.session_state.get("console_pick") not in _opts:
        _pref = st.session_state.selected_hex
        st.session_state.console_pick = _pref if _pref in _opts else _opts[0]

    st.markdown('<span class="ap-label">Target aircraft</span>', unsafe_allow_html=True)
    _chosen = st.selectbox(
        "Target aircraft",
        options=_opts,
        format_func=lambda h: _labels.get(h, h),
        key="console_pick",
        label_visibility="collapsed",
    )
    st.session_state.selected_hex = _chosen
    _run = st.button("Analyze", type="primary", **_FULL, key="run_similarity")

    if _run or st.session_state.trigger_similar:
        st.session_state.trigger_similar = False
        with st.spinner("Computing kinematic & recurrence matches..."):
            _fetched = api_get("/similar", {"hex_": _chosen, "limit": 5})
        st.session_state.similar_result = {"for": _chosen, "data": _fetched}

    _stored = st.session_state.similar_result
    if not _stored or _stored.get("for") != _chosen:
        st.markdown(
            '<div class="ap-empty" style="margin-top:1rem;">Select an aircraft and press '
            "<b>Analyze</b> to see its closest matches.</div>",
            unsafe_allow_html=True,
        )
        return
    _res = _stored.get("data")
    if not isinstance(_res, dict):
        st.markdown(
            '<div class="ap-alert" style="margin-top:1rem;"><b>NO RESULT</b><br/>'
            "The similarity service returned nothing for this aircraft.</div>",
            unsafe_allow_html=True,
        )
        return

    _t = next((a for a in _an if a["hex"] == _chosen), None) or _res.get("reference_anomaly")
    st.markdown('<span class="ap-label">Target</span>', unsafe_allow_html=True)
    if _t:
        _hdg = _headings.get(_chosen)
        _details = _txt(_t.get("details"))
        _prov = _txt(_t.get("explanation_provider"))
        _prov_lbl = f"AI explanation · {_esc(_prov)}" if _prov else "AI explanation"
        _rec = _res.get("recurrence_summary") if isinstance(_res.get("recurrence_summary"), dict) else {}
        _rec_line = ""
        if _rec:
            _rec_line = (
                f'<div class="ap-tel-cell" style="grid-column:1/-1;"><p class="ap-tel-label">Recurrence</p>'
                f'<p class="ap-tel-value">Prior hex: {int(_rec.get("hex_prior_count", 0))} · '
                f'24h regime: {int(_rec.get("regime_count_24h", 0))}</p></div>'
            )
        st.markdown(
            f'<div class="ap-target">'
            f'<div class="ap-target-head">'
            f'<div class="ap-target-id">{_plane_svg(_color(_t.get("anomaly_type", "")), _hdg or 0, 30)}'
            f'<div><p class="ap-target-hex">{_esc(_chosen)}</p>'
            f'<p class="ap-target-callsign">{_esc(_t.get("flight") or "—")}</p></div></div>'
            f'{_badge(_t.get("anomaly_type", ""))}</div>'
            f'<div class="ap-telemetry">'
            f'<div class="ap-tel-cell"><p class="ap-tel-label">Altitude</p><p class="ap-tel-value">{_fmt_alt(_t.get("alt_baro_ft"))}</p></div>'
            f'<div class="ap-tel-cell"><p class="ap-tel-label">Heading</p><p class="ap-tel-value">{_fmt_hdg(_hdg)}</p></div>'
            f'<div class="ap-tel-cell"><p class="ap-tel-label">Latitude</p><p class="ap-tel-value">{_fmt_lat(_t.get("lat"))}</p></div>'
            f'<div class="ap-tel-cell"><p class="ap-tel-label">Longitude</p><p class="ap-tel-value">{_fmt_lon(_t.get("lon"))}</p></div>'
            f'<div class="ap-tel-cell"><p class="ap-tel-label">Last seen</p><p class="ap-tel-value">{_fmt_utc(_t.get("detected_at_ms"))}</p></div>'
            f'<div class="ap-tel-cell"><p class="ap-tel-label">Detections · 60m</p><p class="ap-tel-value">{_det_counts.get(_chosen, 1)}</p></div>'
            f'{_rec_line}'
            f'<div class="ap-tel-cell" style="grid-column:1/-1;"><p class="ap-tel-label">Observation</p>'
            f'<p class="ap-tel-value">{_esc(_details or "—")}</p></div>'
            f'</div>'
            f'<p class="ap-tel-label" style="margin-top:0.6rem;">{_prov_lbl}</p>'
            f'<p class="ap-target-explanation">{_esc(_res.get("query_explanation") or "No explanation recorded.")}</p>'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        st.caption("Target telemetry unavailable.")

    _raw_matches = _res.get("similar_aircraft")
    if _raw_matches is None:
        _raw_matches = _res.get("matches") or []
    _target_ms = _match_detected_ms(_t or {}, _t if isinstance(_t, dict) else None)
    _scored_matches = []
    for m in _raw_matches:
        if not isinstance(m, dict):
            continue
        _m_hex = m.get("hex", "—")
        _m_an = next((a for a in _an if a["hex"] == _m_hex), None)
        _m_ms = _match_detected_ms(m, _m_an)
        raw_score = m.get("similarity_score") if m.get("similarity_score") is not None else m.get("score", 0.0)
        try:
            _base = float(raw_score)
        except (TypeError, ValueError):
            _base = 0.0
        _score = _blended_similarity_score(_base, _target_ms, _m_ms)
        _scored_matches.append((_score, m, _m_an, _m_ms))
    _scored_matches.sort(key=lambda item: item[0], reverse=True)

    st.markdown(f'<span class="ap-label">Closest matches · {len(_scored_matches)}</span>', unsafe_allow_html=True)
    if not _scored_matches:
        st.markdown('<div class="ap-empty">No similar anomalies found yet.</div>', unsafe_allow_html=True)
    for i, (_score, m, _m_an, _m_ms) in enumerate(_scored_matches):
        _m_hex = m.get("hex", "—")
        _m_flight = m.get("flight") or (_m_an or {}).get("flight") or ""
        _id_html = f"<span>{_esc(_m_flight)}</span> · {_esc(_m_hex)}" if _m_flight else _esc(_m_hex)
        _pct = max(2, min(100, int(_score * 100)))
        _det_str = _fmt_utc(_m_ms)
        _summary_parts = [
            f"Detected: {_det_str}",
            f"Alt: {_fmt_alt(m.get('alt_baro_ft'))}",
            f"Phase: {m.get('phase') or '—'}",
            f"Obs: {m.get('details') or '—'}",
        ]
        _expl_preview = m.get("explanation") or " · ".join(_summary_parts)
        _det_line = f'<div class="ap-match-text" style="margin-bottom:0.35rem;">Detected: {_esc(_det_str)}</div>'
        st.markdown(
            f'<div class="ap-match"><div class="ap-match-head">'
            f'<span class="ap-match-rank">{i + 1:02d}</span>'
            f'<span class="ap-match-id">{_id_html}</span>'
            f'<span class="ap-match-score">{_score:.3f}</span></div>'
            f'<div class="ap-bar"><div class="ap-bar-fill" style="width:{_pct}%;"></div></div>'
            f'{_det_line}'
            f'<div class="ap-match-text">{_esc(_expl_preview)}</div></div>',
            unsafe_allow_html=True,
        )

        _m_key = f"{_chosen}_{_m_hex}_{_m_ms or i}_{i}"
        _is_exp = _m_key in st.session_state.expanded_matches
        st.button(
            "Hide details" if _is_exp else "Expand details",
            key=f"exp_match_{_m_key}",
            on_click=_toggle_match_expand,
            args=(_m_key, _m_hex),
            **_FULL,
        )

        if _is_exp:
            _lat, _lon = _match_coords(m, _m_an)
            _m_hdg = _headings.get(_m_hex)
            _m_obs = _txt(m.get("details") or (_m_an or {}).get("details"))
            _expl_state_key = f"expl_open_{_m_key}"
            if _expl_state_key not in st.session_state:
                st.session_state[_expl_state_key] = False

            st.markdown(
                f'<div class="ap-target" style="margin-top:0.45rem;margin-bottom:0.75rem;">'
                f'<div class="ap-telemetry" style="margin-top:0;">'
                f'{_tel("Altitude", _fmt_alt(m.get("alt_baro_ft") if m.get("alt_baro_ft") is not None else (_m_an or {}).get("alt_baro_ft")))}'
                f'{_tel("Heading", _fmt_hdg(_m_hdg))}'
                f'{_tel("Latitude", _fmt_lat(_lat))}'
                f'{_tel("Longitude", _fmt_lon(_lon))}'
                f'{_tel("Position", _fmt_coords(_lat, _lon))}'
                f'{_tel("Detected", _esc(_det_str))}'
                f'<div class="ap-tel-cell" style="grid-column:1/-1;"><p class="ap-tel-label">Observation</p>'
                f'<p class="ap-tel-value">{_esc(_m_obs or "—")}</p></div>'
                f'</div></div>',
                unsafe_allow_html=True,
            )

            if st.button(
                "Hide explanation" if st.session_state[_expl_state_key] else "Explanation",
                key=f"btn_match_expl_{_m_key}",
                type="primary",
                **_FULL,
            ):
                st.session_state[_expl_state_key] = not st.session_state[_expl_state_key]
                if st.session_state[_expl_state_key] and _m_hex and _m_hex != "—":
                    _get_explanation(_m_hex)
                _rerun_fragment()

            if st.session_state[_expl_state_key]:
                if m.get("explanation"):
                    _m_expl_text = m["explanation"]
                elif _m_hex and _m_hex != "—":
                    _, _m_expl_text = _get_explanation(_m_hex)
                else:
                    _m_expl_text = "No explanation available for this record."
                st.markdown(
                    f'<div class="ap-expl" style="margin-top:0.5rem;margin-bottom:0.85rem;">'
                    f'<span class="ap-expl-label">AI explanation</span>'
                    f'{_esc(_m_expl_text)}</div>',
                    unsafe_allow_html=True,
                )


if st.session_state.similarity_open:
    with st.sidebar:
        _render_similarity_tab()


# ---------- Brief + KPI ----------
b_col, k_col = st.columns([1.35, 1], gap="large")

@st.fragment(run_every=CACHE_TTL)
def _render_brief_panel(fallback_brief, df_events: pd.DataFrame) -> None:
    live_brief = _fetch("/airspace/brief")
    brief_obj = live_brief if isinstance(live_brief, dict) else fallback_brief
    st.markdown('<p class="ap-section-title">Current brief</p>', unsafe_allow_html=True)
    if not brief_obj:
        st.markdown(
            '<div class="ap-empty">No brief available yet. Waiting for the brief DAG to complete.</div>',
            unsafe_allow_html=True,
        )
    elif isinstance(brief_obj, dict) and brief_obj.get("_error"):
        st.error(f"Brief unavailable: {brief_obj['_error']}")
    else:
        st.markdown(f'<div class="ap-brief">{_esc(brief_obj.get("text", "—"))}</div>', unsafe_allow_html=True)
        _note = " · last persisted" if brief_obj.get("stale") else ""
        st.markdown(
            f'<span class="ap-label">Source · {_esc(brief_obj.get("provider", "—"))}{_note}</span>',
            unsafe_allow_html=True,
        )
        if not df_events.empty:
            _rep_df = (
                df_events.groupby(["hex", "flight"], as_index=False)
                .size()
                .rename(columns={"size": "events"})
            )
            _rep_df = _rep_df[_rep_df["events"] > 1].sort_values("events", ascending=False)
            if not _rep_df.empty:
                _rep_tags = ", ".join(
                    f"{_esc(r.flight or r.hex)} ({_esc(r.hex)}: {int(r.events)}x)"
                    for r in _rep_df.head(5).itertuples()
                )
                st.markdown(
                    f'<div class="ap-label">Repeat aircraft (window) · {_rep_tags}</div>',
                    unsafe_allow_html=True,
                )


with b_col:
    _render_brief_panel(_brief, df_all)
        # if isinstance(_stats, dict) and isinstance(_stats.get("by_type"), dict) and _stats["by_type"]:
        #     _win_lbl = int(_stats.get("window_minutes") or 60)
        #     _reg_tags = ", ".join(
        #         f"{_esc(k)}: {int(v)}" for k, v in sorted(_stats["by_type"].items())
        #     )
        #     st.markdown(
        #         f'<div class="ap-label">Active regime counts ({_win_lbl}m) · {_reg_tags}</div>',
        #         unsafe_allow_html=True,
        #     )

with k_col:
    _win = 60
    if isinstance(_stats, dict):
        try:
            _win = int(_stats.get("window_minutes") or 60)
        except (TypeError, ValueError):
            _win = 60
    st.markdown(f'<p class="ap-section-title">Anomaly telemetry · {_win} min</p>', unsafe_allow_html=True)
    if _stats and isinstance(_stats, dict) and not _stats.get("_error"):
        _by = {k: v for k, v in (_stats.get("by_type") or {}).items() if k in VISIBLE_TYPES}
        _reported_total = _stats.get("total_anomalies")
        try:
            _total = int(_reported_total) if _reported_total is not None else sum(_by.values())
        except (TypeError, ValueError):
            _total = sum(_by.values())
        _AMB, _CYN = "#fbbf24", "#22d3ee"

        def _meter(n: int, color: str) -> str:
            w = (n / _total * 100) if _total else 0
            return f'<div class="ap-kpi-meter"><span style="width:{w:.1f}%;background:{color};"></span></div>'

        def _card(label, value, accent, meter, sub):
            return (
                f'<div class="ap-kpi-card" style="--accent:{accent};">'
                f'<p class="ap-kpi-label">{label}</p><p class="ap-kpi-value">{value:,}</p>'
                f'{meter}<p class="ap-kpi-sub">{sub}</p></div>'
            )

        _n_d, _n_h = _by.get("rapid_descent", 0), _by.get("holding_pattern", 0)
        _stack = (
            '<div class="ap-kpi-meter">'
            + (f'<span style="width:{_n_d / _total * 100:.1f}%;background:{_AMB};"></span>' if _total and _n_d else "")
            + (f'<span style="width:{_n_h / _total * 100:.1f}%;background:{_CYN};"></span>' if _total and _n_h else "")
            + "</div>"
        )
        def _pct(n: int) -> str:
            return f"{n / _total * 100:.0f}% of total" if _total else "—"
        _kpi = '<div class="ap-kpi-grid">'
        _kpi += _card("Total anomalies", _total, "#8b949e", _stack, f"all types · {_win} min")
        _kpi += _card("Aircraft", len(_headings), "#4ade80", _meter(0, "#4ade80"), "unique in window")
        if "rapid_descent" in _by:
            _kpi += _card("Rapid descent", _n_d, _AMB, _meter(_n_d, _AMB), _pct(_n_d))
        if "holding_pattern" in _by:
            _kpi += _card("Holding pattern", _n_h, _CYN, _meter(_n_h, _CYN), _pct(_n_h))
        _kpi += "</div>"
        st.markdown(_kpi, unsafe_allow_html=True)
    else:
        st.markdown('<div class="ap-empty">Telemetry unavailable.</div>', unsafe_allow_html=True)


# ---------- Map fragment ----------
@st.fragment
def _render_map(df: pd.DataFrame, now: datetime) -> None:
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    lg, dl, rc = st.columns([3.4, 1.6, 0.9])
    with lg:
        _legend = "<div class='ap-legend'>"
        for _t_key in ("rapid_descent", "holding_pattern"):
            if _t_key in df["type"].values:
                _legend += (
                    f"<span class='ap-legend-item'>{_swatch(TYPE_COLORS[_t_key])}"
                    f"{TYPE_LABELS[_t_key]}</span>"
                )
        _legend += (
            "<span class='ap-legend-note'>Icons point along each aircraft's heading "
            "· map view is preserved between updates</span></div>"
        )
        st.markdown(_legend, unsafe_allow_html=True)
    with dl:
        _download(
            "Download map (GeoJSON)", _roster_geojson(df),
            f"aeropulse_map_{stamp}.geojson", "application/geo+json", "dl_map",
        )
    with rc:
        if st.button("Recenter", key="recenter_map", **_FULL):
            st.session_state.map_view = None
            _rerun_fragment()

    df_map = df.dropna(subset=["lat", "lon"]).copy()
    if df_map.empty:
        st.markdown(
            '<div class="ap-empty">No aircraft positions to plot for the current filters.</div>',
            unsafe_allow_html=True,
        )
        return

    df_map["icon_data"] = df_map["type"].apply(lambda t: _plane_icon(tuple(_color(t)[:3])))
    df_map["hdg"] = df_map["hex"].map(_headings)
    df_map["angle"] = df_map["hdg"].apply(lambda h: 0.0 if pd.isna(h) else (360.0 - float(h)) % 360.0)
    df_map["hdg_str"] = df_map["hdg"].apply(_fmt_hdg)
    df_map["label"] = df_map.apply(
        lambda r: f"{r['flight']} · {r['hex']}" if r["flight"] else r["hex"], axis=1
    )
    df_map["alt_str"] = df_map["alt"].apply(_fmt_alt)
    df_map["tl"] = df_map["type"].map(TYPE_LABELS)
    df_map["time_str"] = df_map["ts"].apply(_fmt_utc)
    df_map["details"] = df_map["details"].apply(_txt)
    df_map["halo"] = df_map["type"].apply(lambda t: _color(t)[:3] + [38])
    df_map = df_map[[
        "hex", "lon", "lat", "icon_data", "angle", "hdg_str", "label",
        "alt_str", "tl", "time_str", "details", "halo",
    ]]

    if st.session_state.map_view is None:
        _lat_span = float(df_map["lat"].max() - df_map["lat"].min())
        _lon_span = float(df_map["lon"].max() - df_map["lon"].min())
        _span = max(_lat_span, _lon_span, 0.1)
        _base_zoom = 11 if len(df_map) <= 1 else max(3, min(11, int(math.floor(math.log2(360 * 800 / (256 * _span))))))
        _zoom_out = 3  # Change to 3 for ~3 clicks out on (-)
        _zoom = max(1, _base_zoom - _zoom_out)
        st.session_state.map_view = {
            "latitude": float(df_map["lat"].median()),
            "longitude": float(df_map["lon"].median()),
            "zoom": _zoom,
        }

    _deck = pdk.Deck(
        map_style=MAP_STYLE,
        initial_view_state=pdk.ViewState(**st.session_state.map_view),
        layers=[
            pdk.Layer(
                "ScatterplotLayer", data=df_map, get_position=["lon", "lat"],
                get_fill_color="halo", radius_min_pixels=16, radius_max_pixels=26, pickable=False,
            ),
            pdk.Layer(
                "IconLayer", id="planes", data=df_map, get_icon="icon_data",
                get_position=["lon", "lat"], get_angle="angle", get_size=30,
                size_scale=1, billboard=False,
                pickable=True, auto_highlight=True,
            ),
        ],
        tooltip={
            "html": (
                "<div style='font-family:SF Mono,monospace;font-size:11px;line-height:1.55;'>"
                "<b>{label}</b><br/>{tl}<br/>{alt_str} · HDG {hdg_str}<br/>"
                "<span style='opacity:0.7'>{details}</span><br/>"
                "<span style='opacity:0.7'>{time_str}</span></div>"
            ),
            "style": {
                "backgroundColor": "#0f1419", "color": "#e6edf3",
                "border": "1px solid #2a3543", "borderRadius": "4px", "padding": "6px 10px",
            },
        },
    )
    _picked = None
    try:
        _event = st.pydeck_chart(
            _deck, on_select="rerun", selection_mode="single-object",
            key="aircraft_map", **_FULL,
        )
        _objs = (_event.selection.get("objects") or {}).get("planes") or []
        if _objs:
            _picked = _objs[0].get("hex")
    except TypeError:
        st.pydeck_chart(_deck, **_FULL)

    _pick_row = df[df["hex"] == _picked] if _picked else df.iloc[0:0]
    if _pick_row.empty:
        st.caption("Click an aircraft on the map to see why it was flagged.")
    else:
        _r = _pick_row.iloc[0]
        _hdg = _headings.get(_r["hex"])
        _status, _text = _get_explanation(_r["hex"])
        _body = (
            _esc(_text) if _status == "ok"
            else f"<span style='color:#8b949e;'>{_esc(_text)}</span>"
        )
        _prov = _txt(_r.get("provider"))
        _prov_lbl = f"AI explanation · {_esc(_prov)}" if _prov else "AI explanation"
        st.markdown(
            f'<div class="ap-target ap-detail"><div class="ap-target-head">'
            f'<div class="ap-target-id">{_plane_svg(_color(_r["type"]), _hdg or 0, 30)}'
            f'<div><p class="ap-target-hex">{_esc(_r["hex"])}</p>'
            f'<p class="ap-target-callsign">{_esc(_r["flight"] or "—")}</p></div></div>'
            f'{_badge(_r["type"])}</div>'
            f'<div class="ap-telemetry">'
            f'{_tel("Altitude", _fmt_alt(_r["alt"]))}{_tel("Heading", _fmt_hdg(_hdg))}'
            f'{_tel("Position", _fmt_coords(_r["lat"], _r["lon"]))}'
            f'{_tel("Last seen", _fmt_utc(_r["ts"]))}'
            f'<div class="ap-tel-cell" style="grid-column:1/-1;"><p class="ap-tel-label">Observation</p>'
            f'<p class="ap-tel-value">{_esc(_txt(_r.get("details")) or "—")}</p></div></div>'
            f'<p class="ap-tel-label" style="margin-top:0.6rem;">{_prov_lbl}</p>'
            f'<p class="ap-target-explanation">{_body}</p></div>',
            unsafe_allow_html=True,
        )
        if st.button("Find similar aircraft", type="primary", key=f"map_sim_{_r['hex']}"):
            _open_similarity(_r["hex"])
            st.rerun()


# ---------- Roster fragment ----------
@st.fragment
def _render_roster(df: pd.DataFrame) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    _n_shown = len(df)

    _PAGE = 10
    _pages = max(1, (_n_shown + _PAGE - 1) // _PAGE)
    if st.session_state.table_page > _pages:
        st.session_state.table_page = 1
    _start = (st.session_state.table_page - 1) * _PAGE
    page_df = df.iloc[_start : _start + _PAGE].reset_index(drop=True)

    th, td = st.columns([4, 1.6])
    with th:
        st.markdown(
            f'<div class="ap-roster-head"><span class="ap-label" style="margin:0;">Roster</span>'
            f'<span class="ap-roster-count">{_start + 1}–{_start + len(page_df)} of {_n_shown}</span></div>',
            unsafe_allow_html=True,
        )
    with td:
        _download("Download roster (CSV)", _roster_csv(df), f"aeropulse_roster_{stamp}.csv",
                  "text/csv", "dl_roster")

    for i, row in page_df.iterrows():
        hx = row["hex"]
        expanded = hx in st.session_state.expanded_rows
        _hdg = _headings.get(hx)
        _rkey = ("rowd_" if row["type"] == "rapid_descent" else "rowh_") + hx

        with _row_container(_rkey):
            # --- Header line: id + badge (left) · buttons (right) ---
            hc1, hc2, hc3 = st.columns([8, 1.3, 1.3])
            with hc1:
                st.markdown(
                    f'<div class="ap-row-head">'
                    f'{_plane_svg(_color(row["type"]), _hdg or 0, 30)}'
                    f'<div class="ap-row-id-text">'
                    f'<p class="ap-row-call">{_esc(row["flight"] or "—")}</p>'
                    f'<span class="ap-hex">{_esc(hx)}</span>'
                    f'</div>'
                    f'{_badge(row["type"])}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with hc2:
                st.button(
                    "Hide" if expanded else "Explain",
                    key=f"ex_{hx}_{i}", on_click=_toggle_explain, args=(hx,), **_FULL,
                )
            with hc3:
                if st.button("Similar", key=f"si_{hx}_{i}", type="primary", **_FULL):
                    _open_similarity(hx)
                    st.rerun()

            # --- Full-width metrics + observation ---
            _obs = _txt(row.get("details"))
            _obs_html = (
                f'<div class="ap-row-obs"><b>Observation</b>{_esc(_obs)}</div>'
                if _obs else ""
            )
            st.markdown(
                f'<div class="ap-row-metrics">'
                f'<div class="ap-m"><span class="ap-m-l">Altitude</span>'
                f'<span class="ap-m-v">{_fmt_alt(row["alt"])}</span></div>'
                f'<div class="ap-m"><span class="ap-m-l">Heading</span>'
                f'<span class="ap-m-v">{_fmt_hdg(_hdg)}</span></div>'
                f'<div class="ap-m"><span class="ap-m-l">Position</span>'
                f'<span class="ap-m-v">{_fmt_coords(row["lat"], row["lon"])}</span></div>'
                f'<div class="ap-m"><span class="ap-m-l">Last seen</span>'
                f'<span class="ap-m-v">{_fmt_utc(row["ts"])}</span></div>'
                f'</div>'
                f'{_obs_html}',
                unsafe_allow_html=True,
            )

            # --- Full-width explanation box (when expanded) ---
            if expanded:
                status, text = _get_explanation(hx)
                _prov = _txt(row.get("provider"))
                _lbl = f"AI explanation · {_esc(_prov)}" if _prov else "AI explanation"
                if status == "ok":
                    st.markdown(
                        f'<div class="ap-expl">'
                        f'<span class="ap-expl-label">{_lbl}</span>'
                        f'{_esc(text)}'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.caption(text)

    # --- Pager ---
    pc1, pc2, pc3 = st.columns([1, 4, 1])
    with pc1:
        if st.button("Previous", disabled=st.session_state.table_page <= 1, **_FULL):
            st.session_state.table_page -= 1
            _rerun_fragment()
    with pc2:
        st.markdown(
            f"<span class='ap-label' style='text-align:center;padding-top:0.2rem;'>"
            f"Page {st.session_state.table_page} / {_pages}</span>",
            unsafe_allow_html=True,
        )
    with pc3:
        if st.button("Next", disabled=st.session_state.table_page >= _pages, **_FULL):
            st.session_state.table_page += 1
            _rerun_fragment()


# ---------- Anomalies: filters + map + roster ----------
st.markdown('<hr class="ap-rule">', unsafe_allow_html=True)
st.markdown('<p class="ap-section-title">Live anomaly roster</p>', unsafe_allow_html=True)

SORTS = ["Newest first", "Altitude · high to low", "Altitude · low to high", "Callsign A–Z"]

if not _an:
    st.markdown(
        '<div class="ap-empty">No anomalies detected in the last 60 minutes.</div>',
        unsafe_allow_html=True,
    )
else:
    df_hex = df_all.drop_duplicates(subset=["hex"], keep="first").reset_index(drop=True)

    f1, f2, f3, f4, f5 = st.columns([2.2, 1.9, 1.9, 1.7, 0.8])
    with f1:
        _q = st.text_input(
            "Search", placeholder="Search callsign or ICAO hex",
            label_visibility="collapsed", key="q_input",
        )
    with f2:
        _types = sorted(df_hex["type"].unique().tolist())
        _sel = st.multiselect(
            "Type", options=_types, default=_types,
            format_func=lambda t: TYPE_LABELS.get(t, t),
            label_visibility="collapsed", placeholder="All types", key="type_filter",
        )
    with f3:
        _alts = df_hex["alt"].dropna()
        if not _alts.empty:
            _lo = int(math.floor(float(_alts.min()) / 100) * 100)
            _hi = int(math.ceil(float(_alts.max()) / 100) * 100)
        else:
            _lo, _hi = 0, 45000
        if _lo == _hi:
            _hi = _lo + 100
        _alt_rng = st.slider(
            "Altitude (ft)", min_value=_lo, max_value=_hi, value=(_lo, _hi),
            step=100, label_visibility="collapsed", key="alt_filter",
        )
    with f4:
        _sort = st.selectbox("Sort", SORTS, label_visibility="collapsed", key="sort_by")
    with f5:
        st.button("Clear", on_click=_clear_filters, **_FULL)

    df = df_hex.copy()
    if _q.strip():
        _n = _q.strip().lower()
        df = df[
            df["flight"].str.lower().str.contains(_n, na=False, regex=False)
            | df["hex"].str.lower().str.contains(_n, na=False, regex=False)
        ]
    if _sel and len(_sel) < len(_types):
        df = df[df["type"].isin(_sel)]
    df = df[df["alt"].isna() | ((df["alt"] >= _alt_rng[0]) & (df["alt"] <= _alt_rng[1]))]
    if _sort == SORTS[1]:
        df = df.sort_values("alt", ascending=False, na_position="last")
    elif _sort == SORTS[2]:
        df = df.sort_values("alt", ascending=True, na_position="last")
    elif _sort == SORTS[3]:
        df = df.assign(_blank=df["flight"].eq("")).sort_values(["_blank", "flight"]).drop(columns="_blank")
    else:
        df = df.sort_values("ts", ascending=False)

    _n_total, _n_shown = len(df_hex), len(df)
    if _n_shown == _n_total:
        st.caption(f"{_n_shown} aircraft with anomalies in the last hour")
    else:
        st.caption(f"{_n_shown} of {_n_total} aircraft match the current filters")

    if df.empty:
        st.markdown('<div class="ap-empty">No aircraft match the current filters.</div>', unsafe_allow_html=True)
    else:
        _render_map(df, now)
        st.markdown('<hr class="ap-rule">', unsafe_allow_html=True)
        _render_roster(df)


# ---------- Footer ----------
st.markdown('<hr class="ap-rule">', unsafe_allow_html=True)
st.markdown(
    f'<p class="ap-footer">Synced <span id="ap-clock-foot">{now.strftime("%Y-%m-%d %H:%M:%S")} UTC</span> · '
    f"cache {CACHE_TTL}s · auto-refresh every {CACHE_TTL}s</p>",
    unsafe_allow_html=True,
)
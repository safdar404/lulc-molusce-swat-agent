"""Streamlit section (v1.2.0): build a thesis-style report from the session's analyses."""
import streamlit as st

import report
import ui


def render(ctx, version):
    ui.section("📄", "Report generator", "Word and print-ready HTML report: methods with your numbers, tables, maps, references and this log", "violet")
    items = report.available(ctx, latest_only=not st.checkbox("Offer every run (not only the latest per analysis)", key="rp_all"))
    if not items:
        st.info("Run analyses in the other tabs (or ask the agent) first; each result is collected here automatically.")
        return
    labels = {i: lab for i, lab in items}
    sel = st.multiselect("Analyses to include (in workflow order)", list(labels), default=list(labels), format_func=labels.get,
                         key=f"rp_sel_{len(items)}_{items[-1][0]}")  # new results re-select everything
    c = st.columns(2)
    title = c[0].text_input("Title", "Land-cover change, simulation and hydrological response", key="rp_title")
    area = c[1].text_input("Study area", key="rp_area")
    c = st.columns(2)
    author = c[0].text_input("Author", key="rp_author")
    inst = c[1].text_input("Institution", key="rp_inst")
    abstract = st.text_area("Summary paragraph (optional, your own words)", key="rp_abs", height=90)
    log = st.checkbox("Append processing log", True, key="rp_log")
    if st.button("📄 Build report", type="primary"):
        with st.spinner("Writing text, tables, maps and charts…"):
            blocks, docx_b, html_b = report.generate(ctx, title, author, inst, area, abstract, sel, log, version)
        ctx.__dict__["report_files"] = {"report.docx": docx_b, "report.html": html_b}
        ctx.record("generate_report", {"title": title, "analyses": len(sel)}, f"{sum(b[0] == 'table' for b in blocks)} tables, "
                   f"{sum(b[0] == 'fig' and bool(b[1]) for b in blocks)} figures")
        st.session_state.rp_outline = [b[1] for b in blocks if b[0] == "h1"]
    files = ctx.__dict__.get("report_files")
    if files:
        if st.session_state.get("rp_outline"):
            st.caption("Sections: " + " · ".join(st.session_state.rp_outline))
        c = st.columns(2)
        c[0].download_button("⬇️ Word report (.docx)", files["report.docx"], "LULC_report.docx",
                             "application/vnd.openxmlformats-officedocument.wordprocessingml.document", key="dl_rep_docx")
        c[1].download_button("⬇️ HTML report (open, then Print → Save as PDF)", files["report.html"], "LULC_report.html", "text/html", key="dl_rep_html")

import os
import tempfile
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

if not os.environ.get("DEEPSEEK_API_KEY"):
    st.error("DEEPSEEK_API_KEY is not set. Add it to your .env file or Railway environment variables.")
    st.stop()

from src.resume_parser import parse_resume
from src.scraper import scrape_jobs
from src.ai_generator import tailor_resume_and_cover_letter
from src.pdf_builder import build_resume_pdf, build_cover_letter_pdf

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="CV Mender", layout="wide")

# ── Session state defaults ─────────────────────────────────────────────────────
_DEFAULTS = {
    "step": 1,
    "resume_data": None,
    "jobs": [],
    "generated": {},
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ── Step indicator ─────────────────────────────────────────────────────────────
def _step_indicator():
    labels = ["1 · Upload Resume", "2 · Search Jobs", "3 · Select Jobs", "4 · Download"]
    cols = st.columns(len(labels))
    for i, (col, label) in enumerate(zip(cols, labels), 1):
        with col:
            if i < st.session_state.step:
                st.success(f"✓ {label}")
            elif i == st.session_state.step:
                st.info(f"▶ {label}")
            else:
                st.text(f"  {label}")


_step_indicator()
st.divider()


# ══════════════════════════════════════════════════════════════════════════════
# Step 1 — Upload Resume
# ══════════════════════════════════════════════════════════════════════════════
if st.session_state.step == 1:
    st.header("Upload your resume")
    st.caption("Accepted formats: PDF, DOCX")

    uploaded = st.file_uploader("Choose file", type=["pdf", "docx"], label_visibility="collapsed")

    if uploaded:
        st.success(f"Loaded: **{uploaded.name}**")
        if st.button("Parse Resume →", type="primary"):
            suffix = Path(uploaded.name).suffix
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(uploaded.read())
                tmp_path = tmp.name

            with st.spinner("Extracting and structuring your resume..."):
                try:
                    st.session_state.resume_data = parse_resume(tmp_path)
                    st.session_state.step = 2
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not parse resume: {exc}")
                finally:
                    os.unlink(tmp_path)


# ══════════════════════════════════════════════════════════════════════════════
# Step 2 — Search Jobs
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.step == 2:
    st.header("Search for jobs")

    col1, col2 = st.columns(2)
    with col1:
        keywords = st.text_input("Job title / keywords", placeholder="e.g. Senior Python Engineer")
    with col2:
        location = st.text_input("Location", placeholder="e.g. London, UK")

    max_jobs = st.slider("Max jobs to fetch", min_value=5, max_value=100, value=25, step=5)

    col_back, col_go = st.columns([1, 4])
    with col_back:
        if st.button("← Back"):
            st.session_state.step = 1
            st.rerun()
    with col_go:
        ready = bool(keywords.strip() and location.strip())
        if st.button("Search LinkedIn →", type="primary", disabled=not ready):
            with st.spinner(f"Scraping LinkedIn for **{keywords}** in **{location}** …"):
                try:
                    jobs = scrape_jobs(keywords.strip(), location.strip(), max_jobs=max_jobs)
                    if not jobs:
                        st.warning("No jobs found. Try different keywords or location.")
                    else:
                        st.session_state.jobs = jobs
                        st.session_state.step = 3
                        st.rerun()
                except RuntimeError as exc:
                    # Surface friendly scraper errors (login wall, etc.)
                    st.error(str(exc))
                except Exception as exc:
                    st.error(f"Scraping failed: {exc}")


# ══════════════════════════════════════════════════════════════════════════════
# Step 3 — Select Jobs
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.step == 3:
    jobs = st.session_state.jobs
    st.header(f"Select jobs to apply to  ({len(jobs)} found)")
    st.caption("Expand a card to read the description, then tick the ones you want.")

    selected: list[int] = []

    for i, job in enumerate(jobs):
        label = f"**{job['title']}** — {job['company']}  |  {job['location']}"
        with st.expander(f"{job['title']}  ·  {job['company']}  ·  {job['location']}"):
            desc = job.get("description", "")
            st.markdown(desc[:800] + ("…" if len(desc) > 800 else "") if desc else "_No description available._")
            if job.get("url"):
                st.markdown(f"[View on LinkedIn]({job['url']})")
            if st.checkbox("Select this job", key=f"sel_{i}"):
                selected.append(i)

    st.write("")
    col_back, col_gen = st.columns([1, 4])
    with col_back:
        if st.button("← Back"):
            st.session_state.step = 2
            st.rerun()
    with col_gen:
        n = len(selected)
        if st.button(
            f"Generate tailored applications for {n} job{'s' if n != 1 else ''} →",
            type="primary",
            disabled=n == 0,
        ):
            selected_jobs = [jobs[i] for i in selected]
            st.session_state.generated = {}
            progress = st.progress(0, text="Starting…")

            for idx, job in enumerate(selected_jobs):
                progress.progress(
                    idx / len(selected_jobs),
                    text=f"Tailoring for {job['title']} @ {job['company']} …",
                )
                try:
                    result = tailor_resume_and_cover_letter(st.session_state.resume_data, job)
                    resume_pdf = build_resume_pdf(result["resume"])
                    cl_pdf = build_cover_letter_pdf(result["cover_letter"], result["resume"], job)
                    key = f"{job['company']}_{job['title']}".replace(" ", "_")
                    st.session_state.generated[key] = {
                        "job": job,
                        "resume_pdf": resume_pdf,
                        "cover_letter_pdf": cl_pdf,
                    }
                except Exception as exc:
                    st.warning(f"Skipped {job['title']} @ {job['company']}: {exc}")

            progress.progress(1.0, text="Done!")
            st.session_state.step = 4
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# Step 4 — Download
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.step == 4:
    st.header("Your tailored applications")

    if not st.session_state.generated:
        st.warning("Nothing was generated. Go back and try again.")
    else:
        for key, data in st.session_state.generated.items():
            job = data["job"]
            st.subheader(f"{job['title']}  ·  {job['company']}")
            st.caption(job["location"])

            col1, col2, col3 = st.columns([2, 2, 1])
            with col1:
                st.download_button(
                    label="Download Resume (PDF)",
                    data=data["resume_pdf"],
                    file_name=f"resume_{key}.pdf",
                    mime="application/pdf",
                )
            with col2:
                st.download_button(
                    label="Download Cover Letter (PDF)",
                    data=data["cover_letter_pdf"],
                    file_name=f"cover_letter_{key}.pdf",
                    mime="application/pdf",
                )
            with col3:
                if job.get("url"):
                    st.link_button("View Job", job["url"])

            st.divider()

    if st.button("Start over"):
        for k in _DEFAULTS:
            st.session_state[k] = _DEFAULTS[k]
        st.rerun()

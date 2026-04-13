import os
import tempfile
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ── Bootstrap (runs once per process) ─────────────────────────────────────────
from src.database import init_db
init_db()

from src.scheduler import start_scheduler
start_scheduler()  # no-op after first call — singleton via st.cache_resource

# ── API key guard ──────────────────────────────────────────────────────────────
if not os.environ.get("DEEPSEEK_API_KEY"):
    st.set_page_config(page_title="CV Mender", layout="wide")
    st.error(
        "**DEEPSEEK_API_KEY** is not set. "
        "Add it to your `.env` file or Railway environment variables and restart."
    )
    st.stop()

# ── App-level imports ──────────────────────────────────────────────────────────
from src.database import (
    get_config, save_config,
    get_jobs, get_stats, get_job_pdfs,
    insert_jobs, touch_last_scraped,
    set_job_status, save_job_pdfs,
)
from src.resume_parser import parse_resume
from src.scraper import scrape_jobs
from src.ai_generator import tailor_resume_and_cover_letter
from src.pdf_builder import build_resume_pdf, build_cover_letter_pdf

st.set_page_config(page_title="CV Mender", layout="wide")

# ── Helpers ────────────────────────────────────────────────────────────────────

_STATUS_LABEL = {
    "new":       ("🔵", "New"),
    "generated": ("🟢", "Generated"),
    "applied":   ("✅", "Applied"),
    "removed":   ("🗑️", "Removed"),
}


def _time_ago(dt_str: str | None) -> str:
    if not dt_str:
        return "never"
    try:
        dt = datetime.fromisoformat(dt_str)
    except ValueError:
        return dt_str
    delta = datetime.now() - dt
    if delta.days >= 1:
        return f"{delta.days}d ago"
    h = delta.seconds // 3600
    if h >= 1:
        return f"{h}h ago"
    m = delta.seconds // 60
    return f"{m}m ago" if m >= 1 else "just now"


def _safe_filename(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in text)


# ── Sidebar ────────────────────────────────────────────────────────────────────

config = get_config()
is_configured = bool(config and config.get("keywords") and config.get("resume_data"))

with st.sidebar:
    st.title("CV Mender")
    st.divider()

    if is_configured:
        st.caption(f"**Keywords:** {config['keywords']}")
        st.caption(f"**Location:** {config['location']}")
        st.caption(f"**Last scraped:** {_time_ago(config.get('last_scraped_at'))}")
        st.caption("Next auto-scrape: ~24 h after last")
        st.divider()

        if st.button("Scrape Now", use_container_width=True, type="primary"):
            with st.spinner("Scraping LinkedIn…"):
                try:
                    jobs = scrape_jobs(
                        config["keywords"],
                        config["location"],
                        max_jobs=config.get("max_jobs", 25),
                    )
                    n = insert_jobs(jobs)
                    touch_last_scraped()
                    st.success(f"{n} new job(s) added.")
                    st.rerun()
                except RuntimeError as exc:
                    st.error(str(exc))
                except Exception as exc:
                    st.error(f"Scrape failed: {exc}")

        st.divider()

    page = st.radio(
        "Page",
        ["Dashboard", "Settings"],
        label_visibility="collapsed",
    )

    if not is_configured and page == "Dashboard":
        st.info("Complete **Settings** first to start tracking jobs.")


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

if page == "Dashboard":

    if not is_configured:
        st.header("Welcome to CV Mender")
        st.write("Head to **Settings** in the sidebar to upload your resume and configure your job search. After that, jobs will be scraped daily and appear here.")
        st.stop()

    # ── Stats row ──────────────────────────────────────────────────────────────
    stats = get_stats()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Jobs", stats.get("total") or 0)
    c2.metric("🔵 New", stats.get("new") or 0)
    c3.metric("🟢 Generated", stats.get("generated") or 0)
    c4.metric("✅ Applied", stats.get("applied") or 0)

    st.divider()

    # ── Filter tabs ────────────────────────────────────────────────────────────
    tab_all, tab_new, tab_gen, tab_applied, tab_removed = st.tabs(
        ["All", "New", "Generated", "Applied", "Removed"]
    )

    # ── Job card renderer ──────────────────────────────────────────────────────

    def _job_card(job: dict) -> None:
        jid = job["id"]
        status = job["status"]
        icon, label = _STATUS_LABEL.get(status, ("", status))

        with st.container(border=True):
            left, right = st.columns([3, 2])

            with left:
                st.markdown(
                    f"{icon} &nbsp;**{job['title']}**&nbsp;&nbsp;"
                    f"<span style='color:grey;font-size:0.85em'>{label}</span>",
                    unsafe_allow_html=True,
                )
                st.caption(
                    f"{job['company']}  ·  {job['location']}  ·  "
                    f"scraped {_time_ago(job['scraped_at'])}"
                    + (
                        f"  ·  generated {_time_ago(job['generated_at'])}"
                        if job.get("generated_at")
                        else ""
                    )
                )
                if job.get("description"):
                    with st.expander("Description"):
                        st.markdown(
                            job["description"][:1200]
                            + ("…" if len(job["description"]) > 1200 else "")
                        )
                        if job.get("url"):
                            st.markdown(f"[View on LinkedIn ↗]({job['url']})")

            with right:
                _job_actions(job, jid, status)

    def _job_actions(job: dict, jid: int, status: str) -> None:
        """Render action buttons in the right column of a job card."""

        if status == "removed":
            if st.button("Restore", key=f"restore_{jid}", use_container_width=True):
                set_job_status(jid, "new")
                st.rerun()
            return

        # ── Generate / Re-generate ─────────────────────────────────────────────
        btn_label = "Generate PDFs" if status == "new" else "Regenerate PDFs"
        if st.button(btn_label, key=f"gen_{jid}", use_container_width=True):
            with st.spinner(f"Tailoring for {job['title']} @ {job['company']}…"):
                try:
                    result = tailor_resume_and_cover_letter(
                        config["resume_data"], job
                    )
                    r_pdf = build_resume_pdf(result["resume"])
                    cl_pdf = build_cover_letter_pdf(
                        result["cover_letter"], result["resume"], job
                    )
                    save_job_pdfs(jid, r_pdf, cl_pdf)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Failed: {exc}")

        # ── Downloads (only after generation) ─────────────────────────────────
        if status in ("generated", "applied"):
            pdfs = get_job_pdfs(jid)
            company_slug = _safe_filename(job["company"])
            title_slug = _safe_filename(job["title"])

            st.download_button(
                "Download Resume",
                data=pdfs.get("resume_pdf") or b"",
                file_name=f"resume_{company_slug}_{title_slug}.pdf",
                mime="application/pdf",
                key=f"dl_res_{jid}",
                use_container_width=True,
            )
            st.download_button(
                "Download Cover Letter",
                data=pdfs.get("cover_letter_pdf") or b"",
                file_name=f"cover_letter_{company_slug}_{title_slug}.pdf",
                mime="application/pdf",
                key=f"dl_cl_{jid}",
                use_container_width=True,
            )

        # ── Status transitions ─────────────────────────────────────────────────
        if status == "generated":
            if st.button(
                "Mark as Applied", key=f"apply_{jid}", use_container_width=True
            ):
                set_job_status(jid, "applied")
                st.rerun()

        if status == "applied":
            if st.button(
                "Unmark Applied", key=f"unapply_{jid}", use_container_width=True,
                type="secondary",
            ):
                set_job_status(jid, "generated")
                st.rerun()

        # ── Remove ─────────────────────────────────────────────────────────────
        st.write("")  # spacing
        if st.button(
            "Remove", key=f"rm_{jid}", use_container_width=True, type="secondary"
        ):
            set_job_status(jid, "removed")
            st.rerun()

    # ── Render tabs ────────────────────────────────────────────────────────────

    def _render_job_list(jobs: list) -> None:
        if not jobs:
            st.caption("No jobs in this category.")
            return
        for job in jobs:
            _job_card(job)

    with tab_all:
        _render_job_list(get_jobs())

    with tab_new:
        _render_job_list(get_jobs("new"))

    with tab_gen:
        _render_job_list(get_jobs("generated"))

    with tab_applied:
        _render_job_list(get_jobs("applied"))

    with tab_removed:
        removed = get_jobs("removed")
        if removed:
            st.caption(
                "These jobs are hidden from your main dashboard. "
                "Restore any you want to reconsider."
            )
            _render_job_list(removed)
        else:
            st.caption("No removed jobs.")


# ══════════════════════════════════════════════════════════════════════════════
# SETTINGS
# ══════════════════════════════════════════════════════════════════════════════

elif page == "Settings":
    st.header("Settings")

    existing = config or {}

    # ── Resume upload ──────────────────────────────────────────────────────────
    st.subheader("Resume")
    if is_configured:
        current_name = existing.get("resume_data", {}).get("name", "")
        st.caption(f"Current resume belongs to: **{current_name}**")

    uploaded = st.file_uploader(
        "Upload resume (PDF or DOCX) — leave blank to keep the current one",
        type=["pdf", "docx"],
    )

    # ── Search parameters ──────────────────────────────────────────────────────
    st.subheader("Job Search")
    col1, col2 = st.columns(2)
    with col1:
        keywords = st.text_input(
            "Job title / keywords",
            value=existing.get("keywords", ""),
            placeholder="e.g. Senior Python Engineer",
        )
    with col2:
        location = st.text_input(
            "Location",
            value=existing.get("location", ""),
            placeholder="e.g. London, UK",
        )

    max_jobs = st.slider(
        "Max jobs per scrape",
        min_value=5,
        max_value=100,
        value=existing.get("max_jobs", 25),
        step=5,
        help="Higher values take longer but surface more opportunities.",
    )

    st.divider()

    col_save, col_save_scrape = st.columns(2)

    with col_save:
        save_only = st.button("Save settings", use_container_width=True)
    with col_save_scrape:
        save_and_scrape = st.button(
            "Save & Scrape Now", type="primary", use_container_width=True
        )

    if save_only or save_and_scrape:
        # Validate
        resume_data = existing.get("resume_data")

        if uploaded:
            suffix = Path(uploaded.name).suffix
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(uploaded.read())
                tmp_path = tmp.name
            with st.spinner("Parsing resume…"):
                try:
                    resume_data = parse_resume(tmp_path)
                except Exception as exc:
                    st.error(f"Could not parse resume: {exc}")
                    os.unlink(tmp_path)
                    st.stop()
                finally:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)

        errors = []
        if not resume_data:
            errors.append("Upload a resume — none is saved yet.")
        if not keywords.strip():
            errors.append("Job title / keywords cannot be empty.")
        if not location.strip():
            errors.append("Location cannot be empty.")

        if errors:
            for e in errors:
                st.error(e)
            st.stop()

        save_config(resume_data, keywords.strip(), location.strip(), max_jobs)
        st.success("Settings saved.")

        if save_and_scrape:
            with st.spinner(f"Scraping LinkedIn for **{keywords}** in **{location}**…"):
                try:
                    jobs = scrape_jobs(keywords.strip(), location.strip(), max_jobs=max_jobs)
                    n = insert_jobs(jobs)
                    touch_last_scraped()
                    st.success(f"Done — {n} new job(s) added. Go to the Dashboard.")
                    st.rerun()
                except RuntimeError as exc:
                    st.error(str(exc))
                except Exception as exc:
                    st.error(f"Scrape failed: {exc}")

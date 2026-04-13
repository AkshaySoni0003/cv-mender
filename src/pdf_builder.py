from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def _render(template_name: str, context: dict) -> str:
    env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=True)
    return env.get_template(template_name).render(**context)


def _to_pdf(html: str) -> bytes:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        pdf_bytes = page.pdf(
            format="A4",
            print_background=True,
            margin={"top": "15mm", "bottom": "15mm", "left": "18mm", "right": "18mm"},
        )
        browser.close()
    return pdf_bytes


def build_resume_pdf(resume_data: dict) -> bytes:
    html = _render("resume.html", resume_data)
    return _to_pdf(html)


def build_cover_letter_pdf(
    cover_letter_text: str, resume_data: dict, job: dict
) -> bytes:
    # Split plain text into paragraphs for the template
    paragraphs = [p.strip() for p in cover_letter_text.split("\n\n") if p.strip()]

    context = {
        "name": resume_data["name"],
        "email": resume_data.get("email", ""),
        "phone": resume_data.get("phone", ""),
        "date": date.today().strftime("%B %d, %Y"),
        "company": job["company"],
        "job_title": job["title"],
        "paragraphs": paragraphs,
    }
    html = _render("cover_letter.html", context)
    return _to_pdf(html)

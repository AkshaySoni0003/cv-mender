import json
import os
from pathlib import Path

from openai import OpenAI


def _deepseek_client() -> OpenAI:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise EnvironmentError("DEEPSEEK_API_KEY is not set.")
    return OpenAI(api_key=api_key, base_url="https://api.deepseek.com")


def parse_resume(file_path: str) -> dict:
    """
    Extract text from a PDF or DOCX resume and return structured JSON via DeepSeek.
    """
    ext = Path(file_path).suffix.lower()

    if ext == ".pdf":
        raw_text = _extract_pdf(file_path)
    elif ext == ".docx":
        raw_text = _extract_docx(file_path)
    else:
        raise ValueError(f"Unsupported file type: {ext}. Use PDF or DOCX.")

    if not raw_text.strip():
        raise ValueError("Could not extract any text from the resume file.")

    return _structure_with_deepseek(raw_text)


def _extract_pdf(path: str) -> str:
    import pdfplumber

    parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                parts.append(text)
    return "\n".join(parts)


def _extract_docx(path: str) -> str:
    from docx import Document

    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


_RESUME_SCHEMA = """{
  "name": "string",
  "email": "string",
  "phone": "string",
  "location": "string",
  "linkedin": "string or null",
  "portfolio": "string or null",
  "summary": "string or null",
  "experience": [
    {
      "title": "string",
      "company": "string",
      "location": "string or null",
      "dates": "string",
      "bullets": ["string"]
    }
  ],
  "education": [
    {
      "degree": "string",
      "institution": "string",
      "dates": "string",
      "details": "string or null"
    }
  ],
  "skills": ["string"],
  "certifications": ["string"]
}"""


def _structure_with_deepseek(raw_text: str) -> dict:
    client = _deepseek_client()

    response = client.chat.completions.create(
        model="deepseek-chat",
        max_tokens=4096,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a resume parser. Extract structured information and return "
                    "ONLY valid JSON — no markdown, no explanation, no code fences."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Parse this resume into the following JSON schema:\n\n"
                    f"{_RESUME_SCHEMA}\n\n"
                    f"Resume:\n{raw_text}"
                ),
            },
        ],
    )

    content = response.choices[0].message.content.strip()

    # Strip markdown code fences if the model wrapped the JSON anyway
    if content.startswith("```"):
        lines = content.splitlines()
        content = "\n".join(
            lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        )

    return json.loads(content)

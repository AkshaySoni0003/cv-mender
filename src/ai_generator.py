import json
import os

from openai import OpenAI


def _deepseek_client() -> OpenAI:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise EnvironmentError("DEEPSEEK_API_KEY is not set.")
    return OpenAI(api_key=api_key, base_url="https://api.deepseek.com")


def tailor_resume_and_cover_letter(resume_data: dict, job: dict) -> dict:
    """
    Tailor the candidate's resume for a specific job and generate a cover letter.
    Returns {"resume": dict, "cover_letter": str}.
    """
    client = _deepseek_client()
    tailored = _tailor_resume(client, resume_data, job)
    cover_letter = _generate_cover_letter(client, tailored, job)
    return {"resume": tailored, "cover_letter": cover_letter}


def _tailor_resume(client: OpenAI, resume: dict, job: dict) -> dict:
    response = client.chat.completions.create(
        model="deepseek-chat",
        max_tokens=4096,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert resume writer. Return ONLY valid JSON — "
                    "no markdown, no explanation, no code fences."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Tailor this resume to better match the job description below.\n\n"
                    "STRICT RULES:\n"
                    "1. Do NOT invent, fabricate, or exaggerate any experience, skills, or achievements.\n"
                    "2. Reorder bullet points so the most relevant ones appear first.\n"
                    "3. Update the professional summary to align with the role and company.\n"
                    "4. Adopt terminology from the job description where it accurately describes "
                    "the candidate's existing experience.\n"
                    "5. Add a skill only if the candidate clearly demonstrates it in their "
                    "experience — do not pad the skills list.\n"
                    "6. Keep changes subtle; preserve the candidate's authentic voice.\n"
                    "7. Return the result in the exact same JSON schema as the input resume.\n\n"
                    f"Job Title: {job['title']}\n"
                    f"Company: {job['company']}\n"
                    f"Location: {job['location']}\n\n"
                    f"Job Description:\n{job.get('description', 'Not available')}\n\n"
                    f"Current Resume:\n{json.dumps(resume, indent=2)}"
                ),
            },
        ],
    )

    content = response.choices[0].message.content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        content = "\n".join(
            lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        )

    return json.loads(content)


def _generate_cover_letter(client: OpenAI, resume: dict, job: dict) -> str:
    recent_exp = json.dumps(resume.get("experience", [])[:2], indent=2)
    top_skills = ", ".join(resume.get("skills", [])[:15])

    response = client.chat.completions.create(
        model="deepseek-chat",
        max_tokens=1024,
        messages=[
            {
                "role": "system",
                "content": "You are a professional cover letter writer.",
            },
            {
                "role": "user",
                "content": (
                    "Write a professional, compelling cover letter body for this job application.\n\n"
                    "REQUIREMENTS:\n"
                    "- Exactly 3–4 paragraphs.\n"
                    "- Opening: Express genuine interest in the specific role and company; "
                    "reference something concrete about the company or role, not generic praise.\n"
                    "- Middle (1–2 paragraphs): Highlight 2–3 specific achievements from the "
                    "candidate's experience that directly address the job requirements.\n"
                    "- Closing: Confident call to action; one sentence.\n"
                    "- Tone: professional but human. No corporate clichés, no 'I am writing to "
                    "express my interest', no 'I believe I would be a great fit'.\n"
                    "- No bullet points.\n"
                    "- Do NOT include date, address headers, salutation, sign-off, or the "
                    "candidate's name — return ONLY the body paragraphs, separated by blank lines.\n\n"
                    f"Candidate: {resume['name']}\n"
                    f"Applying for: {job['title']} at {job['company']}\n"
                    f"Location: {job['location']}\n\n"
                    f"Job Description:\n{job.get('description', 'Not available')}\n\n"
                    f"Candidate Summary: {resume.get('summary', 'N/A')}\n"
                    f"Recent Experience:\n{recent_exp}\n"
                    f"Key Skills: {top_skills}"
                ),
            },
        ],
    )

    return response.choices[0].message.content.strip()

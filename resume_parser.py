"""
Resume Parser — extracts structured candidate data from PDF/DOCX files.
Supports plain regex extraction + optional Gemini API enhancement.
"""

import re
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_text(filepath: str) -> str:
    path = Path(filepath)
    ext = path.suffix.lower()
    if ext == ".pdf":
        return _extract_pdf(path)
    elif ext == ".docx":
        return _extract_docx(path)
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def _extract_pdf(path: Path) -> str:
    import fitz  # PyMuPDF
    doc = fitz.open(str(path))
    text = []
    for page in doc:
        text.append(page.get_text())
    doc.close()
    return "\n".join(text)


def _extract_docx(path: Path) -> str:
    from docx import Document
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs)


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+", re.IGNORECASE)
PHONE_RE = re.compile(
    r"(?:\+?1[-.\s]?)?\(?([0-9]{3})\)?[-.\s]([0-9]{3})[-.\s]([0-9]{4})"
)
LINKEDIN_RE = re.compile(
    r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w-]+/?", re.IGNORECASE
)
URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)

# Common skill keywords (restaurant + general)
RESTAURANT_SKILLS = {
    # FOH
    "serving", "fine dining", "cash handling", "pos system", "micros",
    "toast", "square", "aloha", "lightspeed", "smart serve",
    "customer service", "hospitality", "hosting", "bartending",
    "mixology", "wine knowledge", "table service", "opening",
    "closing", "reservation system", "open table",
    # BOH
    "line cook", "prep cook", "sous chef", "chef", "grill",
    "fryer", "saute", "expediting", "knife skills", "food safety",
    "food handlers", "haccp", "inventory management", "ordering",
    "receiving", "kitchen management", "menu development",
    "plating", "butchery", "baking", "pastry",
    # Management
    "team leadership", "scheduling", "training", "onboarding",
    "inventory", "ordering", "vendor management", "cost control",
    "labour costing", "p&l", "budgeting", "recruiting",
    "performance management", "shift management", "health inspector",
    # General
    "microsoft office", "excel", "google workspace", "slack",
    "communication", "teamwork", "problem solving", "multitasking",
    "time management", "detail oriented", "bilingual", "spanish",
    "english", "french", "mandarin", "punjabi",
}

# Education keywords
EDUCATION_KEYWORDS = [
    "bachelor", "master", "phd", "diploma", "degree", "certificate",
    "associate", "b.a.", "b.s.", "m.a.", "m.s.", "ph.d.",
    "college", "university", "institute", "school", "culinary",
    "george brown", "humber", "seneca", "centennial", "sheridan",
    "ryerson", "toronto metropolitan", "u of t", "university of toronto",
    "mcmaster", "york university", "guelph", "waterloo",
    "cégep", "lasalle college", "dubai",
]

SECTION_HEADERS = re.compile(
    r"^(?:experience|work\s*experience|employment|employment\s*history|"
    r"education|skills|summary|profile|objective|about\s*me|certifications|"
    r"certificates|projects|languages|references|additional)\s*:?$",
    re.IGNORECASE | re.MULTILINE,
)

# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_resume(filepath: str) -> dict:
    """Parse a resume file and return structured candidate data."""
    text = extract_text(filepath)
    if not text.strip():
        raise ValueError("No text could be extracted from the file")

    lines = [l.strip() for l in text.split("\n") if l.strip()]

    result = {
        "name": _extract_name(lines, text),
        "email": _extract_email(text),
        "phone": _extract_phone(text),
        "linkedin": _extract_linkedin(text),
        "skills": _extract_skills(text),
        "education": _extract_education(lines),
        "experience_summary": _extract_experience_summary(text),
        "sections": _detect_sections(text),
        "raw_text": text[:5000],
    }

    return result


def _extract_name(lines: list, full_text: str) -> str:
    """Name is usually the first substantive line before any section headers."""
    skip_words = {"resume", "curriculum vitae", "cv", "application", "page"}
    for line in lines[:15]:
        cleaned = re.sub(r"[^\w\s'.]", "", line).strip()
        if not cleaned:
            continue
        if cleaned.lower() in skip_words:
            continue
        if len(cleaned) < 3 or len(cleaned) > 60:
            continue
        # Skip if it looks like an email or phone
        if EMAIL_RE.match(cleaned) or PHONE_RE.match(cleaned):
            continue
        # Skip if it's a URL
        if URL_RE.match(cleaned):
            continue
        # Should have at least two words (first + last name)
        words = cleaned.split()
        if len(words) >= 2 and len(words) <= 5:
            return cleaned
    return ""


def _extract_email(text: str) -> str:
    match = EMAIL_RE.search(text)
    return match.group(0) if match else ""


def _extract_phone(text: str) -> str:
    match = PHONE_RE.search(text)
    if match:
        groups = match.groups()
        return f"({groups[0]}) {groups[1]}-{groups[2]}"
    return ""


def _extract_linkedin(text: str) -> str:
    match = LINKEDIN_RE.search(text)
    url = match.group(0) if match else ""
    if url and not url.startswith("http"):
        url = "https://" + url
    return url


def _extract_skills(text: str) -> list:
    found = set()
    lower = text.lower()
    for skill in RESTAURANT_SKILLS:
        if skill in lower:
            found.add(skill.title() if len(skill) > 3 else skill)
    # Also try to find a "Skills" section and parse it
    lines = text.split("\n")
    capturing = False
    for line in lines:
        stripped = line.strip()
        lower_line = stripped.lower()
        if lower_line.strip(": ") == "skills" or re.match(r"^skills\s*:?\s*$", lower_line):
            capturing = True
            continue
        if capturing:
            # Stop at next section header
            if SECTION_HEADERS.match(stripped) and not lower_line.startswith(("fine dining", "pos", "micros", "smart serve")):
                break
            # Extract items respecting parenthesized groups
            # Split on comma/bullet but not inside parentheses
            items = re.split(r",\s*(?![^()]*\))", stripped)
            for item in items:
                item = item.strip().strip("•-–,| \t")
                # Remove matched parentheses only (not strip all parens)
                if item.startswith("(") and item.endswith(")"):
                    item = item[1:-1].strip()
                if len(item) > 2 and len(item) < 60 \
                   and not item.lower().startswith(("skills", "education")) \
                   and not item.lower() in ("english", "spanish", "french", "mandarin", "punjabi"):
                    found.add(item.title())
    return sorted(found) if found else []


def _extract_education(lines: list) -> list:
    """Try to extract education entries."""
    entries = []
    in_edu = False
    edu_section_text = ""

    for line in lines:
        lower = line.lower().strip()
        if lower.startswith("education") or lower.startswith("academic"):
            in_edu = True
            continue
        if in_edu:
            # Check for next section header
            if SECTION_HEADERS.match(line) and not lower.startswith(("bachelor", "diploma", "certificate")):
                break
            has_keyword = any(k in lower for k in EDUCATION_KEYWORDS)
            if has_keyword or re.match(r"^\d{4}", line):
                edu_section_text += line + " "

    if edu_section_text.strip():
        entries.append(edu_section_text.strip())

    # If no section-based extraction, scan all lines
    if not entries:
        for line in lines:
            lower = line.lower()
            if any(k in lower for k in EDUCATION_KEYWORDS) and len(line) > 10:
                entries.append(line)

    return entries[:3]


def _extract_experience_summary(text: str) -> str:
    """Extract a brief summary of work experience by scanning line by line."""
    lines = text.split("\n")
    capturing = False
    captured = []
    # Section headers that terminate experience capture
    stop_headers = {"education", "skills", "summary", "profile", "certifications", "projects"}

    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()

        # Detect start of experience section
        if re.match(r"^(?:experience|work\s*experience|employment|employment\s*history)\s*:?\s*$", lower):
            capturing = True
            continue

        # Stop if we hit another section header
        if capturing:
            if lower.strip(": ") in stop_headers or re.match(r"^(?:" + "|".join(stop_headers) + r")\s*:?\s*$", lower):
                break
            if stripped:
                captured.append(stripped)

    summary = " ".join(captured)
    return summary[:500] if summary else ""


def _detect_sections(text: str) -> list:
    """Return a list of detected section names."""
    sections = []
    for match in SECTION_HEADERS.finditer(text):
        sections.append(match.group(0).strip().strip(":").title())
    return sections


# ---------------------------------------------------------------------------
# Gemini enhancement (optional)
# ---------------------------------------------------------------------------

GEMINI_PROMPT = """You are a resume parser. Extract structured candidate information from the resume text below.

Return ONLY valid JSON with these exact fields:
{
  "name": "Full name",
  "email": "email@address.com",
  "phone": "phone number",
  "linkedin": "LinkedIn URL or empty string",
  "skills": ["skill1", "skill2", ...],
  "education": ["education entry 1", ...],
  "experience_summary": "Brief summary of work history",
  "years_of_experience": total_years_numeric,
  "current_role": "Current or most recent job title",
  "current_company": "Current or most recent company",
  "location": "City, Province if mentioned"
}

Resume text:
{text}
"""


def enhance_with_gemini(filepath: str, api_key: str = None, base_url: str = None) -> dict:
    """Use Gemini API to get richer parsed data from a resume."""
    text = extract_text(filepath)[:8000]

    if not api_key:
        logger.warning("No Gemini API key — falling back to regex parser")
        return parse_resume(filepath)

    url = (base_url or "https://generativelanguage.googleapis.com/v1beta/models/"
           "gemini-2.5-flash:generateContent") + f"?key={api_key}"

    payload = {
        "contents": [{
            "parts": [{"text": GEMINI_PROMPT.format(text=text)}]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 2048,
        },
    }

    import requests
    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        raw = data["candidates"][0]["content"]["parts"][0]["text"]

        # Strip markdown fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw.strip())

        parsed = json.loads(raw)
        # Ensure all expected fields exist
        return {
            "name": parsed.get("name", "") or "",
            "email": parsed.get("email", "") or "",
            "phone": parsed.get("phone", "") or "",
            "linkedin": parsed.get("linkedin", "") or "",
            "skills": parsed.get("skills", []) or [],
            "education": parsed.get("education", []) or [],
            "experience_summary": parsed.get("experience_summary", "") or "",
            "years_of_experience": parsed.get("years_of_experience", 0),
            "current_role": parsed.get("current_role", "") or "",
            "current_company": parsed.get("current_company", "") or "",
            "location": parsed.get("location", "") or "",
            "raw_text": text[:5000],
        }
    except Exception as e:
        logger.warning(f"Gemini enhancement failed: {e}")
        return parse_resume(filepath)

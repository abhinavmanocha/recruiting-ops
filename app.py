"""
Recruiting Ops Centre — In-house Applicant Tracking & Interview Management
Flask + file-system JSON storage, single-page frontend.
"""

import json
import logging
import os
import uuid
import shutil
from datetime import datetime, date
from functools import wraps
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory, Response
from werkzeug.utils import secure_filename

app = Flask(__name__)

# ── Password Protection ──
AUTH_USER = os.environ.get("RECRUIT_USER", "admin")
AUTH_PASS = os.environ.get("RECRUIT_PASS", "recruitops")


def check_auth(username, password):
    return username == AUTH_USER and password == AUTH_PASS


def authenticate():
    return Response(
        "Authentication required", 401,
        {"WWW-Authenticate": 'Basic realm="Recruiting Ops Centre"'},
    )


@app.before_request
def require_auth():
    # Allow static assets and the main page without auth for the login flow
    if request.path.startswith("/static/"):
        return None
    auth = request.authorization
    if not auth or not check_auth(auth.username, auth.password):
        return authenticate()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
JOBS_DIR = DATA_DIR / "jobs"
CANDIDATES_DIR = DATA_DIR / "candidates"
INTERVIEWS_DIR = DATA_DIR / "interviews"
EMPLOYEES_DIR = DATA_DIR / "employees"
UPLOADS_DIR = Path(os.environ.get("RECRUIT_UPLOADS_DIR", BASE_DIR / "uploads"))
CLOUD_RUN = os.environ.get("K_SERVICE") is not None

# On Cloud Run, /tmp is writable — everything else is read-only
if CLOUD_RUN:
    UPLOADS_DIR = Path("/tmp/uploads")

for d in [DATA_DIR, JOBS_DIR, CANDIDATES_DIR, INTERVIEWS_DIR, EMPLOYEES_DIR, UPLOADS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

STAGES = ["applied", "screening", "interview", "offer", "hired", "rejected"]
STAGE_DISPLAY = {
    "applied": "Applied",
    "screening": "Screening",
    "interview": "Interview",
    "offer": "Offer",
    "hired": "Hired",
    "rejected": "Rejected",
}
INTERVIEW_TYPES = ["phone", "video", "in-person", "practical", "group"]
DEFAULT_CRITERIA = [
    "Communication",
    "Experience & Skills",
    "Culture Fit",
    "Reliability",
    "Overall Impression",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slug(name):
    return name.lower().replace(" ", "-").replace("/", "-").replace("\\", "-")


def _now_iso():
    return datetime.now().isoformat()


def _today_iso():
    return date.today().isoformat()


def _read_json(path):
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _list_jobs():
    jobs = []
    for folder in sorted(JOBS_DIR.iterdir()):
        if folder.is_dir():
            meta = _read_json(folder / "job.json")
            if meta:
                jobs.append(meta)
    return sorted(jobs, key=lambda j: j.get("created_at", ""), reverse=True)


def _get_job(job_id):
    meta = _read_json(JOBS_DIR / job_id / "job.json")
    return meta


def _save_job(job_id, data):
    (JOBS_DIR / job_id).mkdir(parents=True, exist_ok=True)
    _write_json(JOBS_DIR / job_id / "job.json", data)


def _list_candidates(job_id=None):
    candidates = []
    for folder in sorted(CANDIDATES_DIR.iterdir()):
        if folder.is_dir():
            c = _read_json(folder / "candidate.json")
            if c and (job_id is None or c.get("job_id") == job_id):
                candidates.append(c)
    return sorted(candidates, key=lambda c: c.get("applied_date", ""), reverse=True)


def _get_candidate(candidate_id):
    return _read_json(CANDIDATES_DIR / candidate_id / "candidate.json")


def _save_candidate(candidate_id, data):
    (CANDIDATES_DIR / candidate_id).mkdir(parents=True, exist_ok=True)
    _write_json(CANDIDATES_DIR / candidate_id / "candidate.json", data)


def _list_interviews(candidate_id=None, job_id=None):
    interviews = []
    for folder in sorted(INTERVIEWS_DIR.iterdir()):
        if folder.is_dir():
            iv = _read_json(folder / "interview.json")
            if iv:
                if candidate_id and iv.get("candidate_id") != candidate_id:
                    continue
                if job_id and iv.get("job_id") != job_id:
                    continue
                interviews.append(iv)
    return sorted(interviews, key=lambda iv: iv.get("scheduled_date", ""), reverse=True)


def _get_interview(interview_id):
    return _read_json(INTERVIEWS_DIR / interview_id / "interview.json")


def _save_interview(interview_id, data):
    (INTERVIEWS_DIR / interview_id).mkdir(parents=True, exist_ok=True)
    _write_json(INTERVIEWS_DIR / interview_id / "interview.json", data)


# ---------------------------------------------------------------------------
# Jobs API
# ---------------------------------------------------------------------------


@app.route("/api/jobs", methods=["GET"])
def api_list_jobs():
    jobs = _list_jobs()
    # Enrich with candidate counts per stage
    for j in jobs:
        candidates = _list_candidates(j["id"])
        j["candidate_count"] = len(candidates)
        j["stage_counts"] = {}
        for s in STAGES:
            j["stage_counts"][s] = sum(1 for c in candidates if c.get("stage") == s)
    return jsonify(jobs)


@app.route("/api/jobs", methods=["POST"])
def api_create_job():
    data = request.get_json()
    if not data or not data.get("title"):
        return jsonify({"error": "Title is required"}), 400
    job_id = _slug(data["title"]) + "-" + uuid.uuid4().hex[:6]
    job = {
        "id": job_id,
        "title": data["title"],
        "department": data.get("department", ""),
        "location": data.get("location", ""),
        "status": data.get("status", "active"),
        "employment_type": data.get("employment_type", "full-time"),
        "description": data.get("description", ""),
        "requirements": data.get("requirements", ""),
        "scorecard_criteria": data.get("scorecard_criteria", DEFAULT_CRITERIA),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    _save_job(job_id, job)
    return jsonify(job), 201


@app.route("/api/jobs/<job_id>", methods=["GET"])
def api_get_job(job_id):
    job = _get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    candidates = _list_candidates(job_id)
    job["candidates"] = candidates
    job["interviews"] = _list_interviews(job_id=job_id)
    return jsonify(job)


@app.route("/api/jobs/<job_id>", methods=["PUT"])
def api_update_job(job_id):
    job = _get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    data = request.get_json()
    for field in ["title", "department", "location", "status", "employment_type",
                   "description", "requirements", "scorecard_criteria"]:
        if field in data:
            job[field] = data[field]
    job["updated_at"] = _now_iso()
    _save_job(job_id, job)
    return jsonify(job)


@app.route("/api/jobs/<job_id>", methods=["DELETE"])
def api_delete_job(job_id):
    shutil.rmtree(JOBS_DIR / job_id, ignore_errors=True)
    # Remove candidates linked to this job
    for c in _list_candidates(job_id):
        shutil.rmtree(CANDIDATES_DIR / c["id"], ignore_errors=True)
        _delete_interviews_for_candidate(c["id"])
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Candidates API
# ---------------------------------------------------------------------------


@app.route("/api/candidates", methods=["GET"])
def api_list_candidates():
    job_id = request.args.get("job_id")
    stage = request.args.get("stage")
    search = request.args.get("search", "").lower()
    candidates = _list_candidates(job_id)
    if stage:
        candidates = [c for c in candidates if c.get("stage") == stage]
    if search:
        candidates = [
            c
            for c in candidates
            if search in c.get("name", "").lower()
            or search in c.get("email", "").lower()
        ]
    # Enrich with job title
    for c in candidates:
        job = _get_job(c.get("job_id", ""))
        c["job_title"] = job["title"] if job else "Unknown"
    return jsonify(candidates)


@app.route("/api/candidates", methods=["POST"])
def api_create_candidate():
    data = request.get_json()
    if not data or not data.get("name"):
        return jsonify({"error": "Name is required"}), 400
    candidate_id = _slug(data["name"]) + "-" + uuid.uuid4().hex[:6]
    candidate = {
        "id": candidate_id,
        "name": data["name"],
        "email": data.get("email", ""),
        "phone": data.get("phone", ""),
        "job_id": data.get("job_id", ""),
        "stage": data.get("stage", "applied"),
        "applied_date": data.get("applied_date", _today_iso()),
        "source": data.get("source", ""),
        "notes": data.get("notes", ""),
        "resume_filename": None,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    _save_candidate(candidate_id, candidate)
    return jsonify(candidate), 201


@app.route("/api/candidates/<candidate_id>", methods=["GET"])
def api_get_candidate(candidate_id):
    c = _get_candidate(candidate_id)
    if not c:
        return jsonify({"error": "Candidate not found"}), 404
    job = _get_job(c.get("job_id", ""))
    c["job_title"] = job["title"] if job else "Unknown"
    c["interviews"] = _list_interviews(candidate_id=candidate_id)
    c["scorecard_criteria"] = job.get("scorecard_criteria", DEFAULT_CRITERIA) if job else DEFAULT_CRITERIA
    return jsonify(c)


@app.route("/api/candidates/<candidate_id>", methods=["PUT"])
def api_update_candidate(candidate_id):
    c = _get_candidate(candidate_id)
    if not c:
        return jsonify({"error": "Candidate not found"}), 404
    data = request.get_json()
    for field in ["name", "email", "phone", "job_id", "stage", "applied_date",
                   "source", "notes"]:
        if field in data:
            c[field] = data[field]
    c["updated_at"] = _now_iso()
    _save_candidate(candidate_id, c)
    return jsonify(c)


@app.route("/api/candidates/<candidate_id>/stage", methods=["PUT"])
def api_update_stage(candidate_id):
    c = _get_candidate(candidate_id)
    if not c:
        return jsonify({"error": "Candidate not found"}), 404
    data = request.get_json()
    stage = data.get("stage")
    if stage not in STAGES:
        return jsonify({"error": f"Invalid stage: {stage}"}), 400
    c["stage"] = stage
    c["updated_at"] = _now_iso()
    _save_candidate(candidate_id, c)
    return jsonify(c)


@app.route("/api/candidates/<candidate_id>", methods=["DELETE"])
def api_delete_candidate(candidate_id):
    shutil.rmtree(CANDIDATES_DIR / candidate_id, ignore_errors=True)
    _delete_interviews_for_candidate(candidate_id)
    return jsonify({"ok": True})


@app.route("/api/candidates/<candidate_id>/resume", methods=["POST"])
def api_upload_resume(candidate_id):
    c = _get_candidate(candidate_id)
    if not c:
        return jsonify({"error": "Candidate not found"}), 404
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400
    filename = secure_filename(f"{candidate_id}_{file.filename}")
    file.save(str(UPLOADS_DIR / filename))
    c["resume_filename"] = filename
    c["updated_at"] = _now_iso()
    _save_candidate(candidate_id, c)
    return jsonify(c)


# ---------------------------------------------------------------------------
# Interviews & Scorecards API
# ---------------------------------------------------------------------------


@app.route("/api/interviews", methods=["GET"])
def api_list_interviews():
    candidate_id = request.args.get("candidate_id")
    job_id = request.args.get("job_id")
    upcoming = request.args.get("upcoming")
    interviews = _list_interviews(candidate_id, job_id)
    # Enrich with names
    for iv in interviews:
        c = _get_candidate(iv.get("candidate_id", ""))
        iv["candidate_name"] = c["name"] if c else "Unknown"
        job = _get_job(iv.get("job_id", ""))
        iv["job_title"] = job["title"] if job else "Unknown"
    if upcoming:
        today = _today_iso()
        interviews = [iv for iv in interviews if iv.get("scheduled_date", "") >= today]
    return jsonify(interviews)


@app.route("/api/interviews", methods=["POST"])
def api_create_interview():
    data = request.get_json()
    if not data or not data.get("candidate_id"):
        return jsonify({"error": "candidate_id is required"}), 400
    interview_id = "int-" + uuid.uuid4().hex[:8]
    interview = {
        "id": interview_id,
        "candidate_id": data["candidate_id"],
        "job_id": data.get("job_id", ""),
        "interviewer": data.get("interviewer", ""),
        "scheduled_date": data.get("scheduled_date", _today_iso()),
        "scheduled_time": data.get("scheduled_time", ""),
        "type": data.get("type", "phone"),
        "status": data.get("status", "scheduled"),
        "location_or_link": data.get("location_or_link", ""),
        "ratings": data.get("ratings", {}),
        "notes": data.get("notes", ""),
        "recommendation": data.get("recommendation", ""),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    _save_interview(interview_id, interview)
    # Auto-move candidate to interview stage
    c = _get_candidate(data["candidate_id"])
    if c and c.get("stage") in ("applied", "screening"):
        c["stage"] = "interview"
        c["updated_at"] = _now_iso()
        _save_candidate(c["id"], c)
    return jsonify(interview), 201


@app.route("/api/interviews/<interview_id>", methods=["GET"])
def api_get_interview(interview_id):
    iv = _get_interview(interview_id)
    if not iv:
        return jsonify({"error": "Interview not found"}), 404
    c = _get_candidate(iv.get("candidate_id", ""))
    iv["candidate_name"] = c["name"] if c else "Unknown"
    job = _get_job(iv.get("job_id", ""))
    iv["job_title"] = job["title"] if job else "Unknown"
    return jsonify(iv)


@app.route("/api/interviews/<interview_id>", methods=["PUT"])
def api_update_interview(interview_id):
    iv = _get_interview(interview_id)
    if not iv:
        return jsonify({"error": "Interview not found"}), 404
    data = request.get_json()
    for field in ["interviewer", "scheduled_date", "scheduled_time", "type",
                   "status", "location_or_link", "ratings", "notes", "recommendation"]:
        if field in data:
            iv[field] = data[field]
    iv["updated_at"] = _now_iso()
    _save_interview(interview_id, iv)
    return jsonify(iv)


@app.route("/api/interviews/<interview_id>", methods=["DELETE"])
def api_delete_interview(interview_id):
    shutil.rmtree(INTERVIEWS_DIR / interview_id, ignore_errors=True)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Employees (hired staff — separate from recruiting candidates)
# ---------------------------------------------------------------------------


def _list_employees(search=None):
    employees = []
    for folder in sorted(EMPLOYEES_DIR.iterdir()):
        if folder.is_dir():
            e = _read_json(folder / "employee.json")
            if e:
                # Add paystub count
                paystub_dir = folder / "paystubs"
                e["paystub_count"] = len(list(paystub_dir.glob("*.pdf"))) if paystub_dir.exists() else 0
                employees.append(e)
    if search:
        s = search.lower()
        employees = [e for e in employees if s in e.get("name", "").lower()]
    return sorted(employees, key=lambda e: e.get("name", "").lower())


def _get_employee(emp_id):
    return _read_json(EMPLOYEES_DIR / emp_id / "employee.json")


def _save_employee(emp_id, data):
    (EMPLOYEES_DIR / emp_id).mkdir(parents=True, exist_ok=True)
    _write_json(EMPLOYEES_DIR / emp_id / "employee.json", data)


@app.route("/api/employees", methods=["GET"])
def api_list_employees():
    search = request.args.get("search", "")
    return jsonify(_list_employees(search))


@app.route("/api/employees", methods=["POST"])
def api_create_employee():
    data = request.get_json()
    if not data or not data.get("name"):
        return jsonify({"error": "Name is required"}), 400
    emp_id = _slug(data["name"]) + "-" + uuid.uuid4().hex[:6]
    employee = {
        "id": emp_id,
        "name": data["name"],
        "email": data.get("email", ""),
        "phone": data.get("phone", ""),
        "position": data.get("position", ""),
        "location": data.get("location", ""),
        "status": data.get("status", "active"),
        "start_date": data.get("start_date", ""),
        "sin": data.get("sin", ""),
        "wage": data.get("wage", ""),
        "emergency_contact": data.get("emergency_contact", ""),
        "notes": data.get("notes", ""),
        "certifications": data.get("certifications", {}),
        "documents": data.get("documents", []),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    _save_employee(emp_id, employee)
    return jsonify(employee), 201


@app.route("/api/employees/<emp_id>", methods=["GET"])
def api_get_employee(emp_id):
    e = _get_employee(emp_id)
    if not e:
        return jsonify({"error": "Employee not found"}), 404
    # List paystub files
    paystub_dir = EMPLOYEES_DIR / emp_id / "paystubs"
    paystubs = []
    if paystub_dir.exists():
        for f in sorted(paystub_dir.glob("*.pdf")):
            paystubs.append({"filename": f.name, "size": f.stat().st_size, "modified": f.stat().st_mtime})
    e["paystubs"] = paystubs
    # List documents
    docs_dir = EMPLOYEES_DIR / emp_id / "documents"
    documents = []
    if docs_dir.exists():
        for f in sorted(docs_dir.iterdir()):
            documents.append({"filename": f.name, "size": f.stat().st_size})
    e["documents"] = documents
    return jsonify(e)


@app.route("/api/employees/<emp_id>", methods=["PUT"])
def api_update_employee(emp_id):
    e = _get_employee(emp_id)
    if not e:
        return jsonify({"error": "Employee not found"}), 404
    data = request.get_json()
    for field in ["name", "email", "phone", "position", "location", "status",
                   "start_date", "sin", "wage", "emergency_contact", "notes",
                   "certifications"]:
        if field in data:
            e[field] = data[field]
    e["updated_at"] = _now_iso()
    _save_employee(emp_id, e)
    return jsonify(e)


@app.route("/api/employees/<emp_id>", methods=["DELETE"])
def api_delete_employee(emp_id):
    shutil.rmtree(EMPLOYEES_DIR / emp_id, ignore_errors=True)
    return jsonify({"ok": True})


@app.route("/api/employees/<emp_id>/paystub", methods=["POST"])
def api_upload_paystub(emp_id):
    e = _get_employee(emp_id)
    if not e:
        return jsonify({"error": "Employee not found"}), 404
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    paystub_dir = EMPLOYEES_DIR / emp_id / "paystubs"
    paystub_dir.mkdir(parents=True, exist_ok=True)
    filename = secure_filename(file.filename)
    file.save(str(paystub_dir / filename))
    return jsonify({"filename": filename, "ok": True})


@app.route("/api/employees/<emp_id>/document", methods=["POST"])
def api_upload_document(emp_id):
    e = _get_employee(emp_id)
    if not e:
        return jsonify({"error": "Employee not found"}), 404
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    docs_dir = EMPLOYEES_DIR / emp_id / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)
    filename = secure_filename(file.filename)
    file.save(str(docs_dir / filename))

    # Update employee record with document listing
    doc_entry = {"filename": filename, "uploaded_at": _now_iso()}
    if "documents" not in e:
        e["documents"] = []
    e["documents"].append(doc_entry)
    e["updated_at"] = _now_iso()
    _save_employee(emp_id, e)
    return jsonify(doc_entry)


@app.route("/api/employees/<emp_id>/files/<path:filename>")
def api_serve_employee_file(emp_id, filename):
    filepath = EMPLOYEES_DIR / emp_id / filename
    if not filepath.exists():
        filepath = EMPLOYEES_DIR / emp_id / "paystubs" / filename
    if not filepath.exists():
        filepath = EMPLOYEES_DIR / emp_id / "documents" / filename
    if not filepath.exists() or not filepath.is_file():
        return jsonify({"error": "File not found"}), 404
    return send_from_directory(str(filepath.parent), str(filepath.name))


# ---------------------------------------------------------------------------
# Scorecard criteria templates
# ---------------------------------------------------------------------------


@app.route("/api/scorecard-criteria", methods=["GET"])
def api_get_default_criteria():
    return jsonify(DEFAULT_CRITERIA)


# ---------------------------------------------------------------------------
# Resume Parsing
# ---------------------------------------------------------------------------


@app.route("/api/resume/parse", methods=["POST"])
def api_parse_resume():
    """Upload and parse a resume file. Returns extracted candidate data."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    ext = Path(file.filename).suffix.lower()
    if ext not in (".pdf", ".docx", ".doc"):
        return jsonify({"error": "Only PDF and DOCX files are supported"}), 400

    filename = secure_filename(f"resume_{uuid.uuid4().hex[:8]}{ext}")
    filepath = UPLOADS_DIR / filename
    file.save(str(filepath))

    try:
        # Use Gemini if API key provided
        api_key = request.form.get("api_key", "")
        if api_key:
            from resume_parser import enhance_with_gemini
            result = enhance_with_gemini(str(filepath), api_key=api_key,
                                         base_url=request.form.get("api_base_url"))
        else:
            from resume_parser import parse_resume
            result = parse_resume(str(filepath))

        result["resume_filename"] = filename
        return jsonify(result)
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.exception("Resume parsing failed")
        return jsonify({"error": f"Failed to parse resume: {str(e)}"}), 422


@app.route("/api/resume/parse/<candidate_id>", methods=["POST"])
def api_parse_and_link(candidate_id):
    """Parse a resume and update the candidate record with extracted data."""
    # First parse the resume
    parse_result = api_parse_resume()
    if parse_result.status_code != 200:
        return parse_result

    parsed = parse_result.get_json()
    candidate = _get_candidate(candidate_id)
    if not candidate:
        return jsonify({"error": "Candidate not found"}), 404

    # Update candidate with parsed data (don't overwrite existing fields)
    for field in ["name", "email", "phone"]:
        if parsed.get(field) and not candidate.get(field):
            candidate[field] = parsed[field]
    if parsed.get("resume_filename"):
        candidate["resume_filename"] = parsed["resume_filename"]

    # Store parsed metadata
    candidate["parsed_skills"] = parsed.get("skills", [])
    candidate["parsed_education"] = parsed.get("education", [])
    candidate["parsed_experience"] = parsed.get("experience_summary", "")
    candidate["parsed_current_role"] = parsed.get("current_role", "")
    candidate["parsed_current_company"] = parsed.get("current_company", "")
    candidate["parsed_location"] = parsed.get("location", "")
    candidate["updated_at"] = _now_iso()

    _save_candidate(candidate_id, candidate)
    return jsonify({"parsed": parsed, "candidate": candidate})


# ---------------------------------------------------------------------------
# File serving
# ---------------------------------------------------------------------------


@app.route("/uploads/<filename>")
def serve_upload(filename):
    return send_from_directory(str(UPLOADS_DIR), filename)


@app.route("/")
def index():
    return send_from_directory(str(BASE_DIR / "templates"), "index.html")


# ---------------------------------------------------------------------------
# Helpers (internal)
# ---------------------------------------------------------------------------


def _delete_interviews_for_candidate(candidate_id):
    for iv in _list_interviews(candidate_id=candidate_id):
        shutil.rmtree(INTERVIEWS_DIR / iv["id"], ignore_errors=True)


# ---------------------------------------------------------------------------
# Seed data for demo
# ---------------------------------------------------------------------------


def _seed_demo_data():
    """Create sample data on first run if no jobs exist."""
    if any(JOBS_DIR.iterdir()):
        return

    jobs_data = [
        {
            "title": "Server",
            "department": "FOH",
            "location": "Milton",
            "status": "active",
            "description": "Looking for experienced servers to join our team. Must be available weekends and evenings.",
            "requirements": "• 1+ year serving experience\n• Smart Serve certified\n• Available Fri-Sun evenings",
            "scorecard_criteria": ["Communication", "Serving Experience", "Menu Knowledge", "Culture Fit", "Reliability"],
        },
        {
            "title": "Line Cook",
            "department": "BOH",
            "location": "Milton",
            "status": "active",
            "description": "Experienced line cook for busy kitchen. Must work well under pressure.",
            "requirements": "• 2+ years line cook experience\n• Food Handlers certification\n• Available weekends",
            "scorecard_criteria": ["Knife Skills", "Speed & Efficiency", "Teamwork", "Food Safety", "Reliability"],
        },
        {
            "title": "Bartender",
            "department": "FOH",
            "location": "Milton",
            "status": "active",
            "description": "Energetic bartender for high-volume environment.",
            "requirements": "• Smart Serve required\n• 2+ years bartending\n• Cocktail knowledge",
            "scorecard_criteria": ["Mixology Knowledge", "Speed", "Customer Service", "Cash Handling", "Teamwork"],
        },
    ]

    candidates_data = [
        # Servers
        {"name": "Sarah Johnson", "email": "sarah.j@email.com", "phone": "555-0101", "job_idx": 0, "stage": "applied", "source": "Indeed"},
        {"name": "Mike Chen", "email": "mike.c@email.com", "phone": "555-0102", "job_idx": 0, "stage": "screening", "source": "Referral"},
        {"name": "Emily Davis", "email": "emily.d@email.com", "phone": "555-0103", "job_idx": 0, "stage": "interview", "source": "LinkedIn"},
        {"name": "James Wilson", "email": "james.w@email.com", "phone": "555-0104", "job_idx": 0, "stage": "offer", "source": "Walk-in"},
        {"name": "Lisa Thompson", "email": "lisa.t@email.com", "phone": "555-0105", "job_idx": 0, "stage": "hired", "source": "Indeed"},
        {"name": "Tom Brown", "email": "tom.b@email.com", "phone": "555-0106", "job_idx": 0, "stage": "rejected", "source": "Indeed"},
        # Line Cooks
        {"name": "Carlos Ruiz", "email": "carlos.r@email.com", "phone": "555-0201", "job_idx": 1, "stage": "applied", "source": "Indeed"},
        {"name": "David Kim", "email": "david.k@email.com", "phone": "555-0202", "job_idx": 1, "stage": "screening", "source": "Referral"},
        {"name": "Anna Kowalski", "email": "anna.k@email.com", "phone": "555-0203", "job_idx": 1, "stage": "interview", "source": "LinkedIn"},
        {"name": "Marco Rossi", "email": "marco.r@email.com", "phone": "555-0204", "job_idx": 1, "stage": "applied", "source": "Walk-in"},
        # Bartenders
        {"name": "Jenna Smith", "email": "jenna.s@email.com", "phone": "555-0301", "job_idx": 2, "stage": "interview", "source": "Indeed"},
        {"name": "Ryan Park", "email": "ryan.p@email.com", "phone": "555-0302", "job_idx": 2, "stage": "applied", "source": "Referral"},
    ]

    for jd in jobs_data:
        job_id = _slug(jd["title"]) + "-" + uuid.uuid4().hex[:6]
        job = {
            "id": job_id,
            **jd,
            "employment_type": "full-time",
            "scorecard_criteria": jd["scorecard_criteria"],
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        _save_job(job_id, job)

    for cd in candidates_data:
        candidate_id = _slug(cd["name"]) + "-" + uuid.uuid4().hex[:6]
        jobs = _list_jobs()
        job = jobs[cd["job_idx"]]
        candidate = {
            "id": candidate_id,
            "name": cd["name"],
            "email": cd["email"],
            "phone": cd["phone"],
            "job_id": job["id"],
            "stage": cd["stage"],
            "applied_date": _today_iso(),
            "source": cd["source"],
            "notes": "",
            "resume_filename": None,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        _save_candidate(candidate_id, candidate)

        # Add an interview for interview-stage candidates
        if cd["stage"] == "interview":
            interview_id = "int-" + uuid.uuid4().hex[:8]
            interview = {
                "id": interview_id,
                "candidate_id": candidate_id,
                "job_id": job["id"],
                "interviewer": "Abhinav",
                "scheduled_date": _today_iso(),
                "scheduled_time": "14:00",
                "type": "in-person",
                "status": "scheduled",
                "location_or_link": "SLF Milton",
                "ratings": {},
                "notes": "",
                "recommendation": "",
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            }
            _save_interview(interview_id, interview)


# Only seed when running directly
if __name__ == "__main__":
    print("📋 Recruiting Ops Centre running at http://localhost:5001")
    app.run(debug=True, host='0.0.0.0', port=5001)

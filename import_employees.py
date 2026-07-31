"""
Import employees from the existing paystub system (07_Paystubs folder)
into the Recruiting Ops Centre employee database.

For each employee folder:
- Reads employee.json (personal, employment, certifications, emergency contact)
- Maps fields to the recruiting-ops employee schema
- Copies paystub PDFs into data/employees/<id>/paystubs/
- Creates the employee record

Usage: python import_employees.py [source_dir] [target_dir]
"""
import json
import re
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SOURCE_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else \
    Path(r"D:\000_Companies\St. Louis Bar and Grill - 1001164368 Ontario Ltd\07_Paystubs")
TARGET_DIR = Path(sys.argv[2]) if len(sys.argv) > 2 else BASE_DIR / "data" / "employees"


def slug(name):
    return name.lower().replace(" ", "-").replace("/", "-").replace("\\", "-").strip()


def now_iso():
    return datetime.now().isoformat()


def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def parse_name(full_name):
    """Split 'FIRST LAST' or 'First Middle Last' into first/last."""
    parts = full_name.split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def map_employee(folder_name, emp_data, folder_path):
    """Map the legacy employee.json to the recruiting-ops schema."""
    personal = emp_data.get("personal", {})
    employment = emp_data.get("employment", {})
    emergency = emp_data.get("emergency_contact", {})
    certs = emp_data.get("certifications", {})

    first = personal.get("first_name", "")
    last = personal.get("last_name", "")
    if not first and not last:
        first, last = parse_name(folder_name)

    name = f"{first} {last}".strip()
    if not name:
        name = folder_name

    # Map certifications to simple boolean dict
    certifications = {}
    cert_map = {
        "smart_serve": "Smart Serve",
        "food_handlers": "Food Handler",
        "whmis": "WHMIS",
        "aoda_training": "AODA Training",
    }
    for key, label in cert_map.items():
        val = certs.get(key)
        if isinstance(val, dict):
            has_cert = bool(val.get("number") or val.get("expiry"))
            certifications[label] = has_cert
        elif val:  # string like aoda_training
            certifications[label] = True

    # Status: terminated if termination_date present
    status = "terminated" if employment.get("termination_date") else "active"

    # Emergency contact
    emergency_contact = ""
    if emergency.get("name"):
        emergency_contact = f"{emergency.get('name')} ({emergency.get('relationship', '')}) {emergency.get('phone', '')}".strip()

    emp_id = slug(name) + "-" + uuid.uuid4().hex[:6]

    # Count paystubs
    paystub_count = 0
    for year_dir in folder_path.iterdir():
        if year_dir.is_dir():
            paystub_count += len(list(year_dir.glob("*.pdf")))

    return {
        "id": emp_id,
        "name": name,
        "email": personal.get("email", ""),
        "phone": personal.get("phone", ""),
        "position": employment.get("position", ""),
        "location": "SLF Milton",
        "status": status,
        "start_date": employment.get("start_date", ""),
        "sin": personal.get("sin", ""),
        "wage": employment.get("pay_rate", ""),
        "emergency_contact": emergency_contact,
        "notes": "",
        "certifications": certifications,
        "address": personal.get("address", ""),
        "birthday": personal.get("birthday", ""),
        "uniform": emp_data.get("uniform", {}),
        "vacation_pay": employment.get("vacation_pay", "4"),
        "termination_date": employment.get("termination_date", ""),
        "termination_reason": employment.get("termination_reason", ""),
        "documents": [],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }


def copy_paystubs(folder_path, target_emp_dir):
    """Copy all paystub PDFs from year folders into the target paystubs dir."""
    paystub_dir = target_emp_dir / "paystubs"
    paystub_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for year_dir in sorted(folder_path.iterdir()):
        if not year_dir.is_dir():
            continue
        for pdf in sorted(year_dir.glob("*.pdf")):
            # Prefix with year to keep them ordered
            dest_name = f"{year_dir.name}_{pdf.name}"
            dest = paystub_dir / dest_name
            if not dest.exists():
                shutil.copy2(pdf, dest)
                count += 1
    return count


def main():
    print(f"Source: {SOURCE_DIR}")
    print(f"Target: {TARGET_DIR}")
    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing employees by name to avoid duplicates on re-run
    existing_by_name = {}
    for folder in TARGET_DIR.iterdir():
        if folder.is_dir():
            e = read_json(folder / "employee.json")
            if e:
                existing_by_name[e.get("name", "").lower()] = folder.name

    imported = []
    skipped = []
    updated = []
    total_paystubs = 0

    # Process main employee folders
    source_folders = [f for f in sorted(SOURCE_DIR.iterdir()) if f.is_dir() and not f.name.startswith(("00_", "01_", "02_", "z__"))]
    past_dir = SOURCE_DIR / "z__Past_Employees"
    past_folders = [f for f in sorted(past_dir.iterdir()) if f.is_dir()] if past_dir.exists() else []

    def import_one(folder, employee, is_past=False):
        nonlocal total_paystubs
        name_key = employee["name"].lower()
        if name_key in existing_by_name:
            # Update existing record in place
            emp_id = existing_by_name[name_key]
            target_emp_dir = TARGET_DIR / emp_id
            old = read_json(target_emp_dir / "employee.json") or {}
            employee["id"] = emp_id
            employee["created_at"] = old.get("created_at", now_iso())
            employee["updated_at"] = now_iso()
            # Preserve existing documents list
            employee["documents"] = old.get("documents", [])
            write_json(target_emp_dir / "employee.json", employee)
            n = copy_paystubs(folder, target_emp_dir)
            total_paystubs += n
            updated.append((employee["name"], n))
        else:
            target_emp_dir = TARGET_DIR / employee["id"]
            target_emp_dir.mkdir(parents=True, exist_ok=True)
            write_json(target_emp_dir / "employee.json", employee)
            n = copy_paystubs(folder, target_emp_dir)
            total_paystubs += n
            imported.append((employee["name"], n))
            existing_by_name[name_key] = employee["id"]

    for folder in source_folders:
        emp_data = read_json(folder / "employee.json")
        if not emp_data:
            print(f"  SKIP {folder.name}: no employee.json")
            skipped.append(folder.name)
            continue

        employee = map_employee(folder.name, emp_data, folder)
        import_one(folder, employee)

    # Process past employees (no details, just paystubs, marked terminated)
    for folder in past_folders:
        name = folder.name.replace("_1", "")
        emp_id = slug(name) + "-" + uuid.uuid4().hex[:6]
        employee = {
            "id": emp_id,
            "name": name,
            "email": "",
            "phone": "",
            "position": "",
            "location": "SLF Milton",
            "status": "terminated",
            "start_date": "",
            "sin": "",
            "wage": "",
            "emergency_contact": "",
            "notes": "Past employee (imported from paystub archive)",
            "certifications": {},
            "address": "",
            "birthday": "",
            "uniform": {},
            "vacation_pay": "4",
            "termination_date": "",
            "termination_reason": "",
            "documents": [],
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        import_one(folder, employee)

    print(f"\n{'='*50}")
    print(f"Imported {len(imported)} new, updated {len(updated)} existing, {total_paystubs} paystubs copied")
    if skipped:
        print(f"Skipped {len(skipped)} folders: {skipped}")
    for name, n in sorted(imported):
        print(f"  🆕 {name}: {n} paystubs")
    if updated:
        for name, n in sorted(updated):
            print(f"  🔄 {name}: {n} paystubs")


if __name__ == "__main__":
    main()

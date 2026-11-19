"""Read applicant lists exported from LinkedIn (Recruiter, Job Posting applicant export, or a
hand-made sheet) into normalised rows. Header names vary between exports, so each target field
accepts several aliases, matched case- and punctuation-insensitively."""

import csv
import io
import re

ALIASES = {
    "first_name": ["first name", "firstname", "given name"],
    "last_name": ["last name", "lastname", "surname", "family name"],
    "applicant_name": ["name", "full name", "candidate name", "applicant name", "candidate"],
    "email": ["email", "email address", "e-mail", "primary email", "contact email"],
    "phone": ["phone", "phone number", "mobile", "mobile number", "contact phone", "phone numbers"],
    "location": ["location", "city", "candidate location", "address"],
    "profile_url": ["profile url", "linkedin profile", "linkedin url", "public profile url", "profile", "linkedin"],
    "headline": ["headline", "current title", "title", "current position", "position"],
    "company": ["current company", "company"],
    "applied_on": ["applied on", "application date", "date applied", "applied date", "applied"],
    "notes": ["notes", "note", "comments"],
}


def _key(text):
    return re.sub(r"[^a-z]", "", (text or "").lower())


_LOOKUP = {_key(alias): field for field, aliases in ALIASES.items() for alias in aliases}

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def decode(data):
    """Bytes from an uploaded file -> text (UTF-8 with or without BOM, else UTF-16, else cp1252)."""
    if isinstance(data, str):
        return data
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = data.decode(encoding)
            if "\x00" not in text:
                return text
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def map_headers(headers):
    """{original header: field} for the headers that are recognised."""
    out = {}
    for header in headers or []:
        field = _LOOKUP.get(_key(header))
        if field and field not in out.values():
            out[header] = field
    return out


def parse_rows(text):
    """CSV text -> (rows, problems). Each row is a dict of the ALIASES fields plus ``row`` (1-based
    line in the sheet). Rows without a usable email are reported in ``problems`` and skipped."""
    text = decode(text)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    mapping = map_headers(reader.fieldnames)
    problems = []
    if "email" not in mapping.values():
        return [], ["No email column found. Expected a header such as 'Email' or 'Email Address'."]

    rows, seen = [], set()
    for line, raw in enumerate(reader, start=2):
        row = {field: (raw.get(header) or "").strip() for header, field in mapping.items()}
        if not any(row.values()):
            continue
        email = row.get("email", "").split(",")[0].split(";")[0].strip().lower()
        if not EMAIL.match(email):
            problems.append(f"Row {line}: no valid email ({row.get('email') or 'empty'}), skipped.")
            continue
        if email in seen:
            problems.append(f"Row {line}: {email} appears more than once, skipped.")
            continue
        seen.add(email)
        row["email"] = email
        if not row.get("applicant_name"):
            row["applicant_name"] = " ".join(p for p in (row.get("first_name"), row.get("last_name")) if p) or email
        if row.get("phone"):
            row["phone"] = row["phone"].split(",")[0].split(";")[0].strip()
        url = row.get("profile_url") or ""
        if url and not url.startswith("http"):
            row["profile_url"] = "https://" + url.lstrip("/")
        row["row"] = line
        rows.append(row)
    return rows, problems

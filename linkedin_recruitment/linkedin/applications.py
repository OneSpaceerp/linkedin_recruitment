"""Turn an Apply Connect ``EXPORT_JOB_APPLICATION`` push event into a flat applicant record.

Voluntary self-identification answers (disability, gender, race, veteran status) are never
kept: ``redact`` removes them before the payload is stored, and ``parse`` does not read them.
"""

import copy
from datetime import UTC, datetime

from . import constants as C

SENSITIVE_KEYS = {"voluntarySelfIdentificationQuestionResponses", "verificationData"}


def redact(payload):
    """Deep copy without EEO answers and verification signals, safe to store for audit."""
    clean = copy.deepcopy(payload or {})

    def walk(node):
        if isinstance(node, dict):
            for key in list(node):
                if key in SENSITIVE_KEYS:
                    node[key] = "[redacted]"
                else:
                    walk(node[key])
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(clean)
    return clean


def _text(node):
    if isinstance(node, dict):
        return (node.get("value") or "").strip() if isinstance(node.get("value"), str) else ""
    return node.strip() if isinstance(node, str) else ""


def _phone(node):
    if not isinstance(node, dict):
        return ""
    number = (node.get("nationalNumber") or "").strip()
    if not number:
        return ""
    code = (node.get("countryCode") or "").strip().lstrip("+")
    phone = f"+{code} {number}" if code else number
    if node.get("extension"):
        phone += f" ext. {node['extension']}"
    return phone


def _location(node):
    if not isinstance(node, dict):
        return ""
    parts = [_text(node.get(k)) for k in ("locationCityAnswer", "locationStateAnswer", "locationCountryAnswer")]
    seen, out = set(), []
    for part in parts:
        for piece in (p.strip() for p in part.split(",")):
            if piece and piece.lower() not in seen:
                seen.add(piece.lower())
                out.append(piece)
    return ", ".join(out)


def _answer(answer):
    """SimpleAnswerValue -> printable string."""
    if not isinstance(answer, dict):
        return ""
    for key, value in answer.items():
        if not isinstance(value, dict):
            continue
        k = key.lower()
        if k == "textanswervalue" or ("value" in value and isinstance(value.get("value"), str)):
            return value.get("value") or ""
        if k == "multiplechoiceanswervalue":
            return ", ".join(value.get("symbolicNames") or [])
        if k == "numericanswervalue":
            v = value.get("integerValue", value.get("decimalValue"))
            return "" if v is None else str(v)
        if k == "phonenumberanswervalue":
            return _phone(value)
        if k == "dateanswervalue":
            d = value.get("date") or {}
            return "-".join(str(d[p]).zfill(2) for p in ("year", "month", "day") if d.get(p))
        if k == "documentanswervalue":
            return value.get("mediaUrl") or ""
        if k == "booleananswervalue":
            return "Yes" if value.get("value") else "No"
    return ""


def _custom(responses, section):
    out = []
    for r in responses or []:
        if isinstance(r, dict):
            out.append({"section": section, "question": r.get("questionIdentifier") or "", "answer": _answer(r.get("answer"))})
    return out


def _range(node):
    rng = (node or {}).get("dateRange") or {}

    def fmt(d):
        return "-".join(str(d[p]).zfill(2) for p in ("year", "month") if d and d.get(p))

    start, end = fmt(rng.get("start")), fmt(rng.get("end"))
    return f"{start} to {end or 'present'}" if start else ""


def applied_at(ms):
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=UTC).replace(tzinfo=None)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def parse(payload):
    """EXPORT_JOB_APPLICATION payload -> dict with the fields a Job Applicant needs.

    Raises ValueError when the payload is not an application or lacks the always-present
    contact fields (first name, last name, email).
    """
    if not isinstance(payload, dict):
        raise ValueError("The application payload is not a JSON object.")
    if payload.get("type") and payload["type"] != C.EXPORT_JOB_APPLICATION:
        raise ValueError(f"Unsupported event type {payload['type']!r}.")
    responses = payload.get("questionResponses") or {}
    contact = responses.get("contactInformationQuestionResponses") or {}

    first = _text(contact.get("firstNameAnswer"))
    middle = _text(contact.get("middleNameAnswer"))
    last = _text(contact.get("lastNameAnswer"))
    email = _text(contact.get("emailAnswer")).lower()
    missing = [label for label, value in (("first name", first), ("last name", last), ("email", email)) if not value]
    if missing:
        raise ValueError("The application has no " + ", ".join(missing) + ".")
    if not payload.get("jobApplicationId"):
        raise ValueError("The application has no jobApplicationId.")

    # the sample payload puts locationAnswer next to the sections; the schema puts it in contact info
    location = _location(contact.get("locationAnswer") or responses.get("locationAnswer"))

    resume = (responses.get("resumeQuestionResponses") or {}).get("resumeQuestionAnswer") or {}
    letter = responses.get("coverLetterQuestionResponses") or {}

    work = []
    for w in (responses.get("workQuestionResponses") or {}).get("workExperienceQuestionSetResponses") or []:
        line = " at ".join(p for p in (_text(w.get("title")), _text(w.get("company"))) if p)
        extra = ", ".join(p for p in (_text(w.get("city")), _range(w.get("employmentDates"))) if p)
        if line:
            work.append(f"{line} ({extra})" if extra else line)
    education = []
    for e in (responses.get("educationQuestionResponses") or {}).get("educationExperienceQuestionSetResponses") or []:
        line = ", ".join(p for p in (_text(e.get("degree")), _text(e.get("fieldOfStudy")), _text(e.get("school"))) if p)
        dates = _range(e.get("datesAttended"))
        if line:
            education.append(f"{line} ({dates})" if dates else line)

    answers = _custom(contact.get("customQuestionResponses"), "Contact")
    answers += _custom((responses.get("resumeQuestionResponses") or {}).get("customQuestionResponses"), "Resume")
    answers += _custom(letter.get("customQuestionResponses"), "Cover letter")
    answers += _custom((responses.get("workQuestionResponses") or {}).get("customQuestionResponses"), "Work")
    answers += _custom((responses.get("educationQuestionResponses") or {}).get("customQuestionResponses"), "Education")
    for block in (responses.get("additionalQuestionResponses") or {}).get("customQuestionSetResponses") or []:
        answers += _custom((block or {}).get("customQuestionResponses"), "Additional")

    skills = [s.get("skillName") for s in payload.get("applicantSkills") or [] if isinstance(s, dict) and s.get("skillName")]

    return {
        "job_application_id": payload["jobApplicationId"],
        "external_job_id": payload.get("externalJobId") or "",
        "member_urn": payload.get("jobApplicant") or "",
        "applied_at": applied_at(payload.get("appliedAt")),
        "first_name": first,
        "middle_name": middle,
        "last_name": last,
        "applicant_name": " ".join(p for p in (first, middle, last) if p),
        "email": email,
        "phone": _phone(contact.get("cellphoneNumberQuestionAnswer")),
        "location": location,
        "resume_url": resume.get("mediaUrl") or "",
        "cover_letter_url": (letter.get("coverLetterQuestionAnswer") or {}).get("mediaUrl") or "",
        "cover_letter": _text(letter.get("textCoverLetterQuestionAnswer")),
        "skills": skills,
        "matched_skills": [s.get("skillName") for s in payload.get("applicantSkills") or []
                           if isinstance(s, dict) and s.get("jobMatched") and s.get("skillName")],
        "work_history": work,
        "education": education,
        "answers": answers,
    }


def delivery_error(code, details=None):
    """Body LinkedIn expects with a non-200 response from the application webhook."""
    if code not in C.DELIVERY_ERRORS:
        code = "OTHER"
    err = {"errorCode": code}
    if details:
        err["additionalErrorDetails"] = details
    return {"errors": [err]}

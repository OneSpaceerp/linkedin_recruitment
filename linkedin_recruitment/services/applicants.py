"""Applicants from LinkedIn: Apply Connect webhook events, the Apply with LinkedIn page and file
imports all end here as a LinkedIn Applicant, then (optionally) a Frappe HR Job Applicant."""

import base64
import json
import mimetypes
import re

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from linkedin_recruitment.linkedin import applications as A
from linkedin_recruitment.linkedin import constants as C
from linkedin_recruitment.linkedin import signatures as S
from linkedin_recruitment.linkedin.client import LinkedInAPIError

from .settings import api_error_text, client_secret, get_client, get_settings, with_app_token

MAX_ATTEMPTS = 5
MAX_UPLOAD = 5 * 1024 * 1024
DOCUMENT_TYPES = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/rtf": ".rtf",
    "text/rtf": ".rtf",
    "text/plain": ".txt",
    "application/vnd.oasis.opendocument.text": ".odt",
}
EXTENSIONS = set(DOCUMENT_TYPES.values())


# ----------------------------------------------------------------------------- webhook intake


def receive(raw_body, signature, remote_ip=None):
    """Handle one Apply Connect POST synchronously and cheaply. Returns (http status, body).

    Heavy work (resume download, Job Applicant) runs in a background job after commit, so the
    webhook answers well within LinkedIn's timeout.
    """
    settings = get_settings()
    if not (cint(settings.enabled) and cint(settings.enable_webhook)):
        return 503, A.delivery_error("TRANSIENT_ERROR", {"otherErrorDetails": "Applications are not accepted right now."})

    try:
        payload = json.loads(raw_body or b"{}")
    except ValueError:
        return 400, A.delivery_error("INPUT_VALIDATION_FAILED", {"otherErrorDetails": "Body is not JSON."})

    valid = S.verify_signature(raw_body, signature, client_secret(settings))
    event = frappe.new_doc("LinkedIn Webhook Event")
    event.event_type = (payload.get("type") if isinstance(payload, dict) else "") or "UNKNOWN"
    event.received_on = now_datetime()
    event.signature_valid = 1 if valid else 0
    event.remote_ip = (remote_ip or "")[:140]
    event.payload = json.dumps(A.redact(payload), indent=1, ensure_ascii=False)

    def save(status, error=""):
        event.status = status
        event.error_message = error[:2000]
        event.flags.ignore_permissions = True
        event.insert()

    if not valid:
        event.payload = ""  # unverified content is not kept
        save("Rejected", "X-LI-Signature did not match.")
        return 401, A.delivery_error("SIGNATURE_MISMATCH")
    if event.event_type != C.EXPORT_JOB_APPLICATION:
        save("Ignored", f"Event type {event.event_type} is not handled.")
        return 200, {}

    application_id = payload.get("jobApplicationId") or ""
    existing = frappe.db.get_value("LinkedIn Webhook Event", {"dedupe_key": application_id}, "name") if application_id else None
    if existing:
        return 409, A.delivery_error("DUPLICATE_APPLICATION_RECEIVED",
                                     {"duplicateApplicationErrorDetails": {"duplicateApplicationId": application_id}})

    try:
        parsed = A.parse(payload)
    except ValueError as e:
        save("Failed", str(e))
        return 400, A.delivery_error("MISSING_REQUIRED_RESPONSE", {"otherErrorDetails": str(e)})

    posting = posting_for(parsed["external_job_id"])
    jo_status = frappe.db.get_value("Job Opening", posting.job_opening, "status") if posting else None
    if posting and (posting.status == "Closed" or jo_status != "Open"):
        save("Ignored", "The job is closed.")
        return 410, A.delivery_error("JOB_POSTING_CLOSED")

    event.dedupe_key = application_id
    save("Queued")
    frappe.enqueue("linkedin_recruitment.services.applicants.process_event", queue="default",
                   event_name=event.name, enqueue_after_commit=True)
    return 200, {}


def posting_for(external_job_id):
    if not external_job_id:
        return None
    name = frappe.db.get_value("LinkedIn Job Posting", {"external_job_id": external_job_id})
    if not name:
        # the external id is '<prefix>-<Job Opening>' (or '-rN' after a reopen)
        name = frappe.db.get_value("LinkedIn Job Posting", {"job_opening": external_job_id})
    return frappe.get_doc("LinkedIn Job Posting", name) if name else None


# ---------------------------------------------------------------------------- processing


def process_event(event_name):
    event = frappe.get_doc("LinkedIn Webhook Event", event_name)
    if event.status == "Processed":
        return event
    settings = get_settings()
    event.attempts = cint(event.attempts) + 1
    try:
        parsed = A.parse(json.loads(event.payload or "{}"))
        applicant = upsert_applicant(parsed, source="Apply Connect", settings=settings)
        event.linkedin_applicant = applicant.name
        event.status = "Processed"
        event.processed_on = now_datetime()
        event.error_message = ""
        if not cint(settings.store_raw_payload):
            event.payload = ""
    except Exception as e:
        frappe.db.rollback()
        event.reload()
        event.attempts = cint(event.attempts) + 1
        event.status = "Failed"
        event.error_message = (api_error_text(e) if isinstance(e, LinkedInAPIError) else str(e))[:2000]
        frappe.log_error(title=f"LinkedIn application {event.dedupe_key}")
    event.flags.ignore_permissions = True
    event.save()
    return event


def retry_failed_events():
    for name in frappe.get_all("LinkedIn Webhook Event",
                               filters={"status": ["in", ("Failed", "Queued")], "attempts": ["<", MAX_ATTEMPTS],
                                        "dedupe_key": ["is", "set"],
                                        "received_on": ["<", frappe.utils.add_to_date(now_datetime(), minutes=-10)]},
                               pluck="name", limit=200):
        process_event(name)
        frappe.db.commit()


def upsert_applicant(parsed, source, settings=None, job_opening=None, resume=None):
    """Create (or update) the LinkedIn Applicant and, when enabled, its Job Applicant."""
    settings = settings or get_settings()
    name = frappe.db.get_value("LinkedIn Applicant", {"job_application_id": parsed["job_application_id"]}) \
        if parsed.get("job_application_id") else None
    applicant = frappe.get_doc("LinkedIn Applicant", name) if name else frappe.new_doc("LinkedIn Applicant")

    posting = posting_for(parsed.get("external_job_id"))
    applicant.update({
        "applicant_name": parsed.get("applicant_name") or parsed["email"],
        "first_name": parsed.get("first_name"),
        "last_name": parsed.get("last_name"),
        "email": parsed["email"],
        "phone": parsed.get("phone"),
        "location": parsed.get("location"),
        "source": source,
        "job_opening": job_opening or (posting.job_opening if posting else applicant.job_opening),
        "linkedin_job_posting": posting.name if posting else applicant.linkedin_job_posting,
        "external_job_id": parsed.get("external_job_id"),
        "job_application_id": parsed.get("job_application_id") or None,
        "member_urn": parsed.get("member_urn"),
        "profile_url": parsed.get("profile_url") or applicant.profile_url,
        "headline": parsed.get("headline") or applicant.headline,
        "applied_at": parsed.get("applied_at") or now_datetime(),
        "cover_letter": parsed.get("cover_letter"),
        "skills": ", ".join(parsed.get("skills") or []),
        "work_history": "\n".join(parsed.get("work_history") or []),
        "education": "\n".join(parsed.get("education") or []),
        "answers": json.dumps(parsed.get("answers") or [], indent=1, ensure_ascii=False) if parsed.get("answers") else "",
        "resume_url": parsed.get("resume_url"),
        "cover_letter_url": parsed.get("cover_letter_url"),
    })
    if not applicant.job_opening:
        applicant.status = "Failed"
        applicant.error_message = _("No Job Opening matches LinkedIn job {0}.").format(parsed.get("external_job_id") or "?")
    applicant.flags.ignore_permissions = True
    applicant.save()

    if resume:
        attach_upload(applicant, resume)
    elif applicant.resume_url and not applicant.resume and cint(settings.download_resume):
        download_resume(applicant)

    if applicant.job_opening and cint(settings.create_job_applicant) and not applicant.job_applicant:
        make_job_applicant(applicant, settings)
    if posting:
        from .jobs import count_applicants

        count_applicants(posting.name)
    return applicant


# --------------------------------------------------------------------------------- files


def _file_name(applicant, ext):
    base = re.sub(r"[^\w\- ]", "", applicant.applicant_name or "applicant").strip().replace(" ", "_") or "applicant"
    return f"{base}_CV{ext}"


def save_file(applicant, content, ext):
    doc = frappe.get_doc({
        "doctype": "File", "file_name": _file_name(applicant, ext), "content": content, "is_private": 1,
        "attached_to_doctype": "LinkedIn Applicant", "attached_to_name": applicant.name,
        "attached_to_field": "resume",
    })
    doc.flags.ignore_permissions = True
    doc.insert()
    applicant.db_set("resume", doc.file_url)
    return doc.file_url


def download_resume(applicant):
    """Fetch the short-lived Apply Connect resume link with the application token."""
    settings = get_settings()
    try:
        content, ctype = with_app_token(
            lambda token: get_client(settings).download(applicant.resume_url, token,
                                                       reference=("LinkedIn Applicant", applicant.name)))
    except LinkedInAPIError as e:
        applicant.db_set("error_message", _("Resume not downloaded: {0}").format(api_error_text(e))[:2000])
        return None
    ext = DOCUMENT_TYPES.get(ctype) or mimetypes.guess_extension(ctype or "") or ""
    if ext not in EXTENSIONS:
        applicant.db_set("error_message", _("Resume not stored: unexpected file type {0}.").format(ctype or "?"))
        return None
    return save_file(applicant, content, ext)


def decode_upload(file_name, data_b64):
    """(content, ext) for a CV sent by the apply page; rejects other types and large files."""
    ext = ("." + file_name.rsplit(".", 1)[-1].lower()) if "." in (file_name or "") else ""
    if ext not in EXTENSIONS:
        frappe.throw(_("Upload your CV as PDF, Word, ODT, RTF or text."))
    try:
        content = base64.b64decode((data_b64 or "").split(",", 1)[-1], validate=True)
    except ValueError:
        frappe.throw(_("The file could not be read. Please try again."))
    if not content or len(content) > MAX_UPLOAD:
        frappe.throw(_("The CV must be smaller than {0} MB.").format(MAX_UPLOAD // (1024 * 1024)))
    if ext == ".pdf" and not content.startswith(b"%PDF"):
        frappe.throw(_("This file is not a valid PDF."))
    return content, ext


def attach_upload(applicant, resume):
    content, ext = resume
    return save_file(applicant, content, ext)


# --------------------------------------------------------------------------- Job Applicant


def ensure_source(settings=None):
    settings = settings or get_settings()
    source = settings.applicant_source or "LinkedIn"
    if not frappe.db.exists("Job Applicant Source", source):
        frappe.get_doc({"doctype": "Job Applicant Source", "source_name": source}).insert(ignore_permissions=True)
    return source


def make_job_applicant(applicant, settings=None):
    """Create the Frappe HR Job Applicant, or link the existing one for the same email and opening."""
    settings = settings or get_settings()
    existing = frappe.db.get_value("Job Applicant", {"email_id": applicant.email, "job_title": applicant.job_opening})
    if existing:
        applicant.db_set({"job_applicant": existing, "status": "Duplicate", "error_message": ""})
        _attach_resume(existing, applicant)
        return existing

    jo = frappe.db.get_value("Job Opening", applicant.job_opening, ["designation", "currency"], as_dict=True) or {}
    ja = frappe.new_doc("Job Applicant")
    ja.update({
        "applicant_name": applicant.applicant_name,
        "email_id": applicant.email,
        "phone_number": applicant.phone,
        "job_title": applicant.job_opening,
        "designation": jo.get("designation"),
        "source": ensure_source(settings),
        "cover_letter": _cover_letter(applicant),
        "resume_link": applicant.profile_url if not applicant.resume else None,
    })
    for field, value in (("li_profile_url", applicant.profile_url), ("li_applicant", applicant.name),
                         ("li_application_id", applicant.job_application_id)):
        if ja.meta.has_field(field):
            ja.set(field, value)
    ja.flags.ignore_permissions = True
    ja.flags.ignore_mandatory = True
    ja.insert()
    applicant.db_set({"job_applicant": ja.name, "status": "Imported", "error_message": ""})
    _attach_resume(ja.name, applicant)
    return ja.name


def _cover_letter(applicant):
    parts = [applicant.cover_letter or ""]
    if applicant.headline:
        parts.append(f"{_('Headline')}: {applicant.headline}")
    if applicant.skills:
        parts.append(f"{_('Skills')}: {applicant.skills}")
    if applicant.work_history:
        parts.append(f"{_('Experience')}:\n{applicant.work_history}")
    if applicant.education:
        parts.append(f"{_('Education')}:\n{applicant.education}")
    return "\n\n".join(p for p in parts if p).strip()


def _attach_resume(job_applicant, applicant):
    """Point the Job Applicant's resume at the same private file (a second File record, so Job
    Applicant readers can open it)."""
    resume = frappe.db.get_value("LinkedIn Applicant", applicant.name, "resume")
    if not resume or frappe.db.get_value("Job Applicant", job_applicant, "resume_attachment"):
        return
    source = frappe.db.get_value("File", {"file_url": resume}, ["file_name", "is_private"], as_dict=True) or {}
    frappe.get_doc({
        "doctype": "File", "file_url": resume, "file_name": source.get("file_name") or resume.rsplit("/", 1)[-1],
        "is_private": source.get("is_private", 1), "attached_to_doctype": "Job Applicant",
        "attached_to_name": job_applicant, "attached_to_field": "resume_attachment",
    }).insert(ignore_permissions=True)
    frappe.db.set_value("Job Applicant", job_applicant, "resume_attachment", resume)


# ------------------------------------------------------------------- Apply with LinkedIn page


def open_job(job_opening):
    """The Job Opening when candidates may apply to it through the page, else None."""
    jo = frappe.db.get_value("Job Opening", job_opening,
                             ["name", "job_title", "company", "status", "description", "publish", "location",
                              "employment_type", "designation", "closes_on"], as_dict=True)
    if not jo or jo.status != "Open":
        return None
    if jo.closes_on and str(jo.closes_on) < frappe.utils.today():
        return None
    on_linkedin = frappe.db.exists("LinkedIn Job Posting", {"job_opening": job_opening, "status": ["!=", "Draft"]}) \
        or frappe.db.exists("LinkedIn Post", {"job_opening": job_opening, "status": "Published"})
    return jo if (cint(jo.publish) or on_linkedin) else None


def apply_with_linkedin(identity, job_opening, phone=None, cover_letter=None, resume=None, consent=0):
    settings = get_settings()
    if not (cint(settings.enabled) and cint(settings.enable_apply_with_linkedin)):
        frappe.throw(_("Applying with LinkedIn is not available."))
    if cint(settings.require_consent) and not cint(consent):
        frappe.throw(_("Please accept the privacy notice to apply."))
    if not open_job(job_opening):
        frappe.throw(_("This job is no longer open."))
    if not identity.get("email_verified"):
        frappe.throw(_("Your LinkedIn email address is not verified. Verify it on LinkedIn, then try again."))
    parsed = {
        "job_application_id": None,
        "applicant_name": identity.get("name") or identity["email"],
        "first_name": identity.get("first_name"),
        "last_name": identity.get("last_name"),
        "email": identity["email"],
        "phone": (phone or "").strip()[:40],
        "member_urn": f"urn:li:person:{identity['sub']}" if identity.get("sub") else "",
        "cover_letter": (cover_letter or "").strip()[:10000],
    }
    existing = frappe.db.get_value("LinkedIn Applicant", {"email": parsed["email"], "job_opening": job_opening})
    if existing:
        return frappe.get_doc("LinkedIn Applicant", existing), False
    return upsert_applicant(parsed, source="Apply with LinkedIn", settings=settings, job_opening=job_opening,
                            resume=resume), True

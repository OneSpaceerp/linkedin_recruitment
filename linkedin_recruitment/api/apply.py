# Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
# For license information, please see license.txt

"""Apply with LinkedIn: candidate sign-in (OpenID Connect) and application submit."""

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import cint

from linkedin_recruitment.services import applicants, oauth


def _redirect(location):
    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = location


@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=30, seconds=600)
def start(job):
    """Send the candidate to LinkedIn to sign in."""
    settings = frappe.get_cached_doc("LinkedIn Settings")
    if not (cint(settings.enabled) and cint(settings.enable_apply_with_linkedin)) or not applicants.open_job(job):
        raise frappe.PageDoesNotExistError
    _redirect(oauth.start("apply", job=job))


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=10, seconds=3600)
def submit(job, token, phone=None, cover_letter=None, file_name=None, file_data=None, consent=0):
    """Create the application for the signed-in LinkedIn member. Returns {created, reference}."""
    identity = oauth.get_identity(token)
    if not identity:
        frappe.throw(_("Your LinkedIn sign-in expired. Please sign in again."), title=_("Sign in again"))
    resume = applicants.decode_upload(file_name, file_data) if file_data else None
    applicant, created = applicants.apply_with_linkedin(identity, job, phone=phone, cover_letter=cover_letter,
                                                        resume=resume, consent=consent)
    oauth.forget_identity(token)
    return {"created": created, "reference": applicant.job_applicant or applicant.name}

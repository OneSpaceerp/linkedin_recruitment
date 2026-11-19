# Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
# For license information, please see license.txt

"""/linkedin-apply/<job opening>: candidates sign in with LinkedIn and send their CV."""

from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import cint
from frappe.utils.html_utils import sanitize_html

from linkedin_recruitment.services import applicants, oauth

no_cache = 1
sitemap = 0


def get_context(context):
    settings = frappe.get_cached_doc("LinkedIn Settings")
    if not (cint(settings.enabled) and cint(settings.enable_apply_with_linkedin)):
        raise frappe.PageDoesNotExistError

    job = frappe.form_dict.get("job") or ""
    jo = applicants.open_job(job) if job else None
    token = frappe.form_dict.get("t") or ""
    identity = oauth.get_identity(token) if token else None

    context.no_cache = 1
    context.show_sidebar = 0
    context.no_breadcrumbs = 1
    context.job = jo
    context.title = _("Apply: {0}").format(jo.job_title) if jo else _("Job not available")
    context.description_html = sanitize_html(jo.description or "") if jo else ""
    context.location = ", ".join(p for p in (jo.location, frappe.db.get_value("Company", jo.company, "country")) if p) if jo else ""
    context.identity = identity
    context.token = token if identity else ""
    context.expired = bool(token and not identity)
    context.error = (frappe.form_dict.get("error") or "")[:200]
    context.start_url = f"/api/method/linkedin_recruitment.api.apply.start?job={quote(job)}"
    context.require_consent = cint(settings.require_consent)
    context.privacy_notice = sanitize_html(settings.privacy_notice or "")
    context.logo = "/assets/linkedin_recruitment/images/linkedin-signin.png"
    context.csrf_token = frappe.sessions.get_csrf_token()
    context.metatags = {"title": context.title, "description": jo.job_title if jo else ""}
    return context

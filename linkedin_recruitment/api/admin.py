# Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
# For license information, please see license.txt

"""Settings, accounts, applicants and imports: actions for LinkedIn Managers and HR."""

import frappe
from frappe import _
from frappe.utils import cint

from linkedin_recruitment.linkedin.client import LinkedInAPIError
from linkedin_recruitment.services import applicants, importer, oauth
from linkedin_recruitment.services.settings import (
    MANAGER_ROLES,
    api_error_text,
    app_token,
    get_settings,
    has_role,
    member_token,
    redirect_uri,
    webhook_url,
)


def _manager():
    if not has_role(MANAGER_ROLES):
        frappe.throw(_("Only a LinkedIn Manager or System Manager can do this."), frappe.PermissionError)


@frappe.whitelist()
def setup_info():
    """URLs to register in the LinkedIn developer app."""
    _manager()
    return {"redirect_uri": redirect_uri(), "webhook_url": webhook_url(),
            "https": webhook_url().startswith("https://")}


@frappe.whitelist(methods=["POST"])
def test_connection():
    """Check each enabled feature against LinkedIn and report in plain words."""
    _manager()
    settings = get_settings()
    checks = []
    if not settings.client_id or not settings.get_password("client_secret", raise_exception=False):
        return [{"ok": False, "check": _("Credentials"), "detail": _("Client ID and Client Secret are required.")}]

    if cint(settings.enable_job_posting_api) or cint(settings.enable_apply_connect):
        try:
            app_token(force=True)
            checks.append({"ok": True, "check": _("Application token"),
                           "detail": _("LinkedIn issued a client-credentials token.")})
        except LinkedInAPIError as e:
            checks.append({"ok": False, "check": _("Application token"), "detail": api_error_text(e)})

    if cint(settings.enable_company_posts):
        if not settings.post_account:
            checks.append({"ok": False, "check": _("Company posts"), "detail": _("Choose the LinkedIn Account to post with.")})
        else:
            try:
                member_token(settings.post_account)
                checks.append({"ok": True, "check": _("Company posts"),
                               "detail": _("{0} is connected.").format(settings.post_account)})
            except frappe.ValidationError as e:
                frappe.clear_messages()
                checks.append({"ok": False, "check": _("Company posts"), "detail": str(e)})

    if cint(settings.enable_apply_connect) or cint(settings.enable_webhook):
        https = webhook_url().startswith("https://")
        checks.append({"ok": https, "check": _("Webhook URL"),
                       "detail": webhook_url() if https else _("LinkedIn only calls HTTPS webhooks; this site is served over HTTP.")})
    if not checks:
        checks.append({"ok": True, "check": _("Settings"), "detail": _("Saved. Turn on a feature to test it against LinkedIn.")})
    return checks


@frappe.whitelist(methods=["POST"])
def connect_account(account=None):
    """Start OAuth for a LinkedIn Account; returns the LinkedIn sign-in URL."""
    _manager()
    if account and not frappe.db.exists("LinkedIn Account", account):
        frappe.throw(_("LinkedIn Account {0} does not exist.").format(account))
    return oauth.start("account", account=account)


@frappe.whitelist(methods=["POST"])
def disconnect_account(account):
    _manager()
    doc = frappe.get_doc("LinkedIn Account", account)
    doc.access_token = ""
    doc.refresh_token = ""
    doc.status = "Not Connected"
    doc.expires_at = doc.refresh_expires_at = None
    doc.save()
    return doc.status


@frappe.whitelist(methods=["POST"])
def reload_organizations(account):
    _manager()
    token, doc = member_token(account)
    if not oauth.load_organizations(doc, token):
        frappe.throw(_("LinkedIn did not allow reading this member's company pages. Connect again with the Community Management scopes."))
    doc.save()
    return [o.as_dict() for o in doc.organizations]


@frappe.whitelist(methods=["POST"])
def make_job_applicant(applicant):
    if not frappe.has_permission("LinkedIn Applicant", "write", doc=applicant) or not frappe.has_permission("Job Applicant", "create"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    doc = frappe.get_doc("LinkedIn Applicant", applicant)
    if not doc.job_opening:
        frappe.throw(_("Set the Job Opening first."))
    return applicants.make_job_applicant(doc)


@frappe.whitelist(methods=["POST"])
def download_resume(applicant):
    if not frappe.has_permission("LinkedIn Applicant", "write", doc=applicant):
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    doc = frappe.get_doc("LinkedIn Applicant", applicant)
    if not doc.resume_url:
        frappe.throw(_("LinkedIn sent no resume for this application."))
    return applicants.download_resume(doc)


@frappe.whitelist(methods=["POST"])
def reprocess_event(event):
    _manager()
    doc = applicants.process_event(event)
    return {"status": doc.status, "error": doc.error_message}


@frappe.whitelist(methods=["POST"])
def start_import(import_name):
    if not frappe.has_permission("LinkedIn Applicant Import", "write", doc=import_name):
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    doc = frappe.get_doc("LinkedIn Applicant Import", import_name)
    if doc.status in ("Queued", "In Progress"):
        frappe.throw(_("This import is already running."))
    doc.db_set("status", "Queued")
    frappe.enqueue(importer.run, queue="long", import_name=import_name, enqueue_after_commit=True,
                   job_id=f"linkedin-import-{import_name}", deduplicate=True)
    return "Queued"

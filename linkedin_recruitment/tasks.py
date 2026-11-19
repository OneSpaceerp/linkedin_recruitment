# Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
# For license information, please see license.txt

"""Scheduled jobs (see hooks.scheduler_events). Each one returns quietly when its feature is off."""

import frappe
from frappe.utils import add_days, cint, now_datetime


def _enabled():
    return cint(frappe.db.get_single_value("LinkedIn Settings", "enabled"))


def poll_job_tasks():
    """Every 10 minutes: read LinkedIn's task status for jobs waiting to go live or close."""
    if _enabled():
        from linkedin_recruitment.services.jobs import refresh

        refresh()


def retry_applications():
    """Hourly: process Apply Connect events that failed or were never picked up."""
    if _enabled():
        from linkedin_recruitment.services.applicants import retry_failed_events

        retry_failed_events()


def close_closed_openings():
    """Daily: close LinkedIn jobs whose Job Opening was closed without a save."""
    if _enabled():
        from linkedin_recruitment.services.jobs import close_orphans

        close_orphans()


def check_account_tokens():
    """Daily: renew member tokens that expire within a week, or mark them Expired and tell the
    person who connected the account."""
    if not _enabled():
        return
    from linkedin_recruitment.services.settings import renew_member_token

    week = add_days(now_datetime(), 7)
    for account in frappe.get_all("LinkedIn Account", filters={"status": "Connected", "expires_at": ["<", week]},
                                  fields=["name", "connected_by", "expires_at"]):
        if renew_member_token(account.name):
            frappe.db.commit()
            continue
        if account.expires_at and account.expires_at <= now_datetime():
            frappe.db.set_value("LinkedIn Account", account.name, "status", "Expired")
        _notify_expiry(account)
        frappe.db.commit()


def _notify_expiry(account):
    if not account.connected_by or account.connected_by in ("Guest", "Administrator"):
        return
    frappe.get_doc({
        "doctype": "Notification Log",
        "for_user": account.connected_by,
        "type": "Alert",
        "document_type": "LinkedIn Account",
        "document_name": account.name,
        "subject": frappe._("LinkedIn sign-in for {0} expires soon. Open the account and click Connect.").format(account.name),
    }).insert(ignore_permissions=True)


def purge_old_records():
    """Daily: delete sync logs and processed webhook events past their retention."""
    settings = frappe.get_cached_doc("LinkedIn Settings")
    log_days = cint(settings.log_retention_days) or 90
    event_days = cint(settings.webhook_retention_days) or 180
    frappe.db.delete("LinkedIn Sync Log", {"creation": ["<", add_days(now_datetime(), -log_days)]})
    frappe.db.delete("LinkedIn Webhook Event", {"creation": ["<", add_days(now_datetime(), -event_days)],
                                                "status": ["in", ("Processed", "Ignored", "Rejected")]})

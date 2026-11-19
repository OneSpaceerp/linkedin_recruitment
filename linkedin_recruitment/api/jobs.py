# Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
# For license information, please see license.txt

"""Desk actions on Job Openings, LinkedIn Job Postings and LinkedIn Posts."""

import frappe
from frappe import _

from linkedin_recruitment.services import jobs, posts


def _can(doctype, ptype, name=None):
    if not frappe.has_permission(doctype, ptype, doc=name):
        frappe.throw(_("Not permitted"), frappe.PermissionError)


def _posting_summary(posting):
    return {"name": posting.name, "status": posting.status, "url": posting.linkedin_job_url,
            "error": posting.error_message, "operation": posting.last_operation}


@frappe.whitelist()
def status(job_opening):
    """LinkedIn state of a Job Opening, for its form."""
    _can("Job Opening", "read", job_opening)
    settings = frappe.get_cached_doc("LinkedIn Settings")
    posting = frappe.db.get_value("LinkedIn Job Posting", {"job_opening": job_opening},
                                  ["name", "status", "linkedin_job_url", "error_message", "applicants"], as_dict=True)
    post_list = frappe.get_all("LinkedIn Post", filters={"job_opening": job_opening},
                               fields=["name", "status", "post_url", "published_on"], order_by="creation desc", limit=5)
    return {
        "enabled": bool(settings.enabled),
        "job_api": bool(settings.enabled and settings.enable_job_posting_api),
        "posts": bool(settings.enabled and settings.enable_company_posts),
        "posting": posting,
        "post_list": post_list,
        "can_publish": frappe.has_permission("LinkedIn Job Posting", "create"),
        "can_post": frappe.has_permission("LinkedIn Post", "create"),
    }


@frappe.whitelist(methods=["POST"])
def publish(job_opening):
    _can("Job Opening", "read", job_opening)
    _can("LinkedIn Job Posting", "create")
    return _posting_summary(jobs.publish(job_opening))


@frappe.whitelist(methods=["POST"])
def close(job_opening):
    _can("Job Opening", "read", job_opening)
    _can("LinkedIn Job Posting", "write")
    posting = jobs.close(job_opening)
    if not posting:
        frappe.throw(_("This Job Opening has no LinkedIn job."))
    return _posting_summary(posting)


@frappe.whitelist(methods=["POST"])
def submit_posting(posting, operation=None):
    _can("LinkedIn Job Posting", "write", posting)
    if operation and operation not in ("CREATE", "UPDATE", "RENEW", "CLOSE"):
        frappe.throw(_("Unknown operation."))
    return _posting_summary(jobs.submit(posting, operation))


@frappe.whitelist(methods=["POST"])
def refresh_posting(posting):
    _can("LinkedIn Job Posting", "read", posting)
    jobs.refresh([posting])
    return _posting_summary(frappe.get_doc("LinkedIn Job Posting", posting))


@frappe.whitelist()
def preview_posting(posting):
    """The exact element that would be sent, or the list of problems."""
    _can("LinkedIn Job Posting", "read", posting)
    doc = frappe.get_doc("LinkedIn Job Posting", posting)
    element, problems = jobs.preview(doc)
    return {"element": element, "problems": problems}


@frappe.whitelist(methods=["POST"])
def draft_post(job_opening):
    """Create a Draft LinkedIn Post from the settings template and return its name."""
    _can("Job Opening", "read", job_opening)
    _can("LinkedIn Post", "create")
    post = posts.draft_for_job_opening(job_opening)
    post.insert()
    return post.name


@frappe.whitelist(methods=["POST"])
def publish_post(post):
    _can("LinkedIn Post", "write", post)
    doc = posts.publish(post)
    return {"status": doc.status, "url": doc.post_url, "error": doc.error_message}


@frappe.whitelist(methods=["POST"])
def delete_post(post):
    _can("LinkedIn Post", "write", post)
    doc = posts.delete(post)
    return {"status": doc.status}

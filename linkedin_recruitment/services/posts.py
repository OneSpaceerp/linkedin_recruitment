"""Announce Job Openings on LinkedIn with the Posts API (organization or member feed)."""

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from linkedin_recruitment.linkedin import payloads as P
from linkedin_recruitment.linkedin.client import LinkedInAPIError

from .jobs import apply_url, location_for
from .settings import api_error_text, get_client, get_settings, member_token, require_enabled

DEFAULT_TEMPLATE = "We're hiring! Join {{ doc.company }} as {{ doc.job_title }}{% if location %} in {{ location }}{% endif %}.\n\nApply here: {{ apply_url }}"


def draft_for_job_opening(job_opening_name, settings=None):
    """A new, unsaved LinkedIn Post for the Job Opening, filled from LinkedIn Settings."""
    settings = settings or get_settings()
    jo = frappe.get_doc("Job Opening", job_opening_name)
    link = apply_url(jo, settings)
    context = {"doc": jo, "location": location_for(jo), "apply_url": link}
    post = frappe.new_doc("LinkedIn Post")
    post.job_opening = jo.name
    post.account = settings.post_account
    post.post_as = settings.post_as or "Organization"
    post.visibility = settings.post_visibility or "PUBLIC"
    post.hashtags = settings.hashtags
    post.commentary = frappe.render_template(settings.post_template or DEFAULT_TEMPLATE, context).strip()
    if link:
        post.link_url = link
        post.link_title = jo.job_title
        post.link_description = P.plain_text(jo.description)[:250]
    return post


def author_urn(post, account, settings=None):
    if post.post_as == "Member":
        if not account.member_urn:
            frappe.throw(_("LinkedIn Account {0} has no member id. Connect it again.").format(account.name))
        return account.member_urn
    if post.organization_urn:
        return post.organization_urn
    if account.default_organization:
        return account.default_organization
    settings = settings or get_settings()
    if settings.organization_id:
        return f"urn:li:organization:{settings.organization_id}"
    frappe.throw(_("Set the organization to post as (on the post, the LinkedIn Account or LinkedIn Settings)."))


def _failed(post, message):
    post.status = "Failed"
    post.error_message = message[:2000]
    post.flags.ignore_permissions = True
    post.save()
    return post


def publish(post_name):
    """Create the post on LinkedIn. Errors are stored on the post and returned, not raised."""
    settings = require_enabled()
    post = frappe.get_doc("LinkedIn Post", post_name)
    if post.status == "Published":
        frappe.throw(_("This post is already on LinkedIn."))
    token, account = member_token(post.account)
    author = author_urn(post, account, settings)
    try:
        body = P.post_payload(author, post.commentary, link=post.link_url, title=post.link_title,
                              description=post.link_description, visibility=post.visibility or "PUBLIC",
                              tags=post.hashtags)
    except P.PayloadError as e:
        return _failed(post, "\n".join(e.problems))
    try:
        urn = get_client(settings).create_post(token, body, reference=("LinkedIn Post", post.name))
    except LinkedInAPIError as e:
        return _failed(post, api_error_text(e))
    post.organization_urn = author if author.startswith("urn:li:organization:") else post.organization_urn
    post.post_urn = urn
    post.post_url = P.post_url(urn)
    post.status = "Published"
    post.published_on = now_datetime()
    post.error_message = ""
    post.flags.ignore_permissions = True
    post.save()
    return post


def delete(post_name):
    require_enabled()
    post = frappe.get_doc("LinkedIn Post", post_name)
    if post.status != "Published" or not post.post_urn:
        frappe.throw(_("Only published posts can be deleted from LinkedIn."))
    token, _account = member_token(post.account)
    try:
        get_client().delete_post(token, post.post_urn, reference=("LinkedIn Post", post.name))
    except LinkedInAPIError as e:
        if e.status != 404:  # already gone on LinkedIn
            frappe.throw(api_error_text(e))
    post.status = "Deleted"
    post.flags.ignore_permissions = True
    post.save()
    return post


def announce_job_opening(job_opening_name):
    """Background job for 'Post Automatically': draft, save and publish once."""
    settings = get_settings()
    if not (cint(settings.enabled) and cint(settings.enable_company_posts) and settings.post_account):
        return None
    post = draft_for_job_opening(job_opening_name, settings)
    post.flags.ignore_permissions = True
    post.insert()
    try:
        return publish(post.name)
    except frappe.ValidationError as e:
        return _failed(post, str(e))

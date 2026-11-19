"""3-legged OAuth: connecting a LinkedIn Account (HR / company page admin) and candidate sign-in.

Both flows share one redirect URL. The ``state`` value is random, single use, valid for ten
minutes, and remembers which flow started it and for whom.
"""

import secrets

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from linkedin_recruitment.linkedin import constants as C
from linkedin_recruitment.linkedin.client import LinkedInAPIError

from .settings import api_error_text, get_client, get_settings, redirect_uri, require_enabled, store_member_tokens

STATE_TTL = 600
IDENTITY_TTL = 1800


def _key(kind, token):
    return f"linkedin_recruitment:{kind}:{token}"


def account_scopes(settings):
    scopes = list(C.OIDC_SCOPES) + list(C.MEMBER_POST_SCOPES)
    if cint(settings.enable_company_posts) and (settings.post_as or "Organization") == "Organization":
        scopes += C.ORGANIZATION_SCOPES
    scopes += (settings.extra_scopes or "").split()
    return list(dict.fromkeys(scopes))


def start(flow, **data):
    """Authorization URL for ``flow`` ('account' or 'apply')."""
    settings = require_enabled()
    state = secrets.token_urlsafe(32)
    frappe.cache.set_value(_key("state", state), {"flow": flow, "user": frappe.session.user, **data},
                           expires_in_sec=STATE_TTL)
    scopes = account_scopes(settings) if flow == "account" else list(C.OIDC_SCOPES)
    return get_client(settings).authorize_url(redirect_uri(), scopes, state)


def pop_state(state):
    if not state:
        return None
    key = _key("state", state)
    data = frappe.cache.get_value(key)
    frappe.cache.delete_value(key)
    return data


# ------------------------------------------------------------------------------ account flow


def connect_account(code, state_data):
    """Exchange the code, read the member profile and store the tokens on the LinkedIn Account."""
    settings = get_settings()
    client = get_client(settings)
    body = client.exchange_code(code, redirect_uri())
    token = body["access_token"]
    profile = client.userinfo(token)

    name = state_data.get("account")
    if name and frappe.db.exists("LinkedIn Account", name):
        account = frappe.get_doc("LinkedIn Account", name)
    else:
        account = frappe.new_doc("LinkedIn Account")
        account.account_name = name or profile.get("name") or profile.get("email") or "LinkedIn"
        if frappe.db.exists("LinkedIn Account", account.account_name):
            account = frappe.get_doc("LinkedIn Account", account.account_name)

    store_member_tokens(account, body)
    if not account.scopes:
        account.scopes = " ".join(account_scopes(settings))
    account.member_urn = f"urn:li:person:{profile['sub']}" if profile.get("sub") else account.member_urn
    account.member_name = profile.get("name") or account.member_name
    account.member_email = profile.get("email") or account.member_email
    account.picture_url = profile.get("picture") or ""
    account.connected_by = state_data.get("user")
    account.connected_on = now_datetime()
    load_organizations(account, token, client)
    account.flags.ignore_permissions = True
    account.save()
    return account


def load_organizations(account, token, client=None):
    """Fill the company pages the member administers. Needs an organization admin scope; a 403
    simply leaves the table empty."""
    client = client or get_client()
    try:
        acls = client.organization_acls(token)
    except LinkedInAPIError as e:
        if e.status in (401, 403):
            return False
        raise
    account.set("organizations", [])
    for acl in acls:
        if not acl["organization"]:
            continue
        try:
            org_name = client.organization_name(token, acl["organization"])
        except LinkedInAPIError:
            org_name = ""
        account.append("organizations", {"organization_urn": acl["organization"], "organization_name": org_name,
                                         "role": acl["role"]})
    if not account.default_organization and account.organizations:
        settings = get_settings()
        wanted = f"urn:li:organization:{settings.organization_id}" if settings.organization_id else ""
        match = next((o.organization_urn for o in account.organizations if o.organization_urn == wanted), None)
        account.default_organization = match or account.organizations[0].organization_urn
    return True


# ------------------------------------------------------------------------------- apply flow


def candidate_identity(code):
    """Exchange the code for a candidate and keep only the OpenID profile, for 30 minutes.
    The candidate's token is not stored. Returns the one-time key the apply page uses."""
    client = get_client()
    body = client.exchange_code(code, redirect_uri())
    profile = client.userinfo(body["access_token"])
    if not profile.get("email"):
        frappe.throw(_("LinkedIn did not share an email address for this account."))
    identity = {
        "sub": profile.get("sub"),
        "name": profile.get("name") or " ".join(p for p in (profile.get("given_name"), profile.get("family_name")) if p),
        "first_name": profile.get("given_name") or "",
        "last_name": profile.get("family_name") or "",
        "email": (profile.get("email") or "").lower(),
        "email_verified": bool(profile.get("email_verified")),
        "picture": profile.get("picture") or "",
    }
    key = secrets.token_urlsafe(32)
    frappe.cache.set_value(_key("identity", key), identity, expires_in_sec=IDENTITY_TTL)
    return key


def get_identity(key):
    if not key or len(key) > 100:
        return None
    return frappe.cache.get_value(_key("identity", key))


def forget_identity(key):
    if key:
        frappe.cache.delete_value(_key("identity", key))


def error_text(e):
    return api_error_text(e) if isinstance(e, LinkedInAPIError) else str(e)

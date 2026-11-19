"""LinkedIn Settings access, the API client factory, access tokens and the sync log."""

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, get_datetime, get_url, now_datetime

from linkedin_recruitment.linkedin import constants as C
from linkedin_recruitment.linkedin.client import LinkedInAPIError, LinkedInClient, dumps

CALLBACK_METHOD = "linkedin_recruitment.api.oauth.callback"
WEBHOOK_METHOD = "linkedin_recruitment.api.webhook.apply_connect"
APP_TOKEN_KEY = "linkedin_recruitment:app_token"
MANAGER_ROLES = {"System Manager", "LinkedIn Manager"}
HR_ROLES = MANAGER_ROLES | {"HR Manager", "HR User"}


def get_settings():
    return frappe.get_cached_doc("LinkedIn Settings")


def redirect_uri():
    return get_url(f"/api/method/{CALLBACK_METHOD}")


def webhook_url():
    return get_url(f"/api/method/{WEBHOOK_METHOD}")


def client_secret(settings=None):
    settings = settings or get_settings()
    return settings.get_password("client_secret", raise_exception=False) or ""


def require_enabled(feature=None):
    """Settings when the integration (and ``feature``, a Check fieldname) is on, else a clear error."""
    settings = get_settings()
    if not cint(settings.enabled):
        frappe.throw(_("The LinkedIn integration is disabled. Enable it in LinkedIn Settings."), title=_("LinkedIn"))
    if not settings.client_id or not client_secret(settings):
        frappe.throw(_("Enter the LinkedIn app's Client ID and Client Secret in LinkedIn Settings."), title=_("LinkedIn"))
    if feature and not cint(settings.get(feature)):
        label = settings.meta.get_label(feature)
        frappe.throw(_("Turn on '{0}' in LinkedIn Settings first.").format(_(label)), title=_("LinkedIn"))
    return settings


def has_role(roles):
    return bool(set(frappe.get_roles()) & set(roles))


# ---------------------------------------------------------------------------------- sync log


class SyncLogger:
    """Client logger: one LinkedIn Sync Log per HTTP exchange.

    Logs are written by a short background job so they survive a rollback of the request that
    made the call (a failed publish should still leave its log behind).
    """

    def __init__(self, settings):
        self.bodies = cint(settings.log_request_bodies)
        self.user = frappe.session.user if getattr(frappe.local, "session", None) else "Administrator"

    def __call__(self, entry):
        reference = entry.get("reference") or (None, None)
        row = {
            "operation": (entry.get("operation") or "")[:140],
            "method": entry.get("method"),
            "endpoint": (entry.get("url") or "")[:1000],
            "status_code": entry.get("status") or 0,
            "success": 1 if 200 <= (entry.get("status") or 0) < 300 else 0,
            "duration_ms": entry.get("duration_ms") or 0,
            "attempt": entry.get("attempt") or 1,
            "request_id": entry.get("request_id") or "",
            "error_message": (entry.get("error") or "")[:2000],
            "reference_doctype": reference[0],
            "reference_name": reference[1],
            "user": self.user,
        }
        if self.bodies:
            row["request_body"] = dumps(entry.get("request_body")) if entry.get("request_body") is not None else ""
            row["response_body"] = dumps(entry.get("response_body")) if entry.get("response_body") is not None else ""
        if frappe.flags.in_test or frappe.flags.in_install or frappe.flags.in_migrate:
            insert_log(row)
        else:
            frappe.enqueue("linkedin_recruitment.services.settings.insert_log", queue="short", row=row)


def insert_log(row):
    doc = frappe.get_doc({"doctype": "LinkedIn Sync Log", **row})
    doc.flags.ignore_links = True
    doc.insert(ignore_permissions=True)


def get_client(settings=None):
    settings = settings or get_settings()
    return LinkedInClient(
        settings.client_id,
        client_secret(settings),
        talent_version=settings.talent_api_version or C.DEFAULT_TALENT_VERSION,
        marketing_version=settings.marketing_api_version or C.DEFAULT_MARKETING_VERSION,
        logger=SyncLogger(settings),
    )


def api_error_text(error):
    """LinkedInAPIError -> message for users, with the HTTP status and LinkedIn's request id."""
    text = str(error)
    if isinstance(error, LinkedInAPIError):
        if error.status == 401:
            text = _("LinkedIn rejected the access token: {0}").format(text)
        elif error.status == 403:
            text = _("This LinkedIn app or account is not allowed to do this ({0}). Check the products enabled on the developer app and the granted scopes.").format(text)
        elif error.status == 429:
            text = _("LinkedIn's rate limit was reached. Try again later. ({0})").format(text)
        if error.status:
            text += f" [HTTP {error.status}]"
        if error.request_id:
            text += f" [request {error.request_id}]"
    return text


# ---------------------------------------------------------------------------- application token


def app_token(force=False):
    """2-legged token (Job Posting API, Apply Connect media). Cached until two minutes before expiry."""
    if not force:
        token = frappe.cache.get_value(APP_TOKEN_KEY)
        if token:
            return token
    body = get_client().client_credentials_token()
    ttl = max(60, int(body.get("expires_in") or 1800) - 120)
    frappe.cache.set_value(APP_TOKEN_KEY, body["access_token"], expires_in_sec=ttl)
    return body["access_token"]


def with_app_token(call):
    """Run ``call(token)``; on 401 fetch a fresh token once and retry."""
    try:
        return call(app_token())
    except LinkedInAPIError as e:
        if e.status != 401:
            raise
        frappe.cache.delete_value(APP_TOKEN_KEY)
        return call(app_token(force=True))


# ------------------------------------------------------------------------------- member tokens


def store_member_tokens(account, body):
    account.access_token = body["access_token"]
    account.expires_at = add_to_date(now_datetime(), seconds=int(body.get("expires_in") or 0))
    if body.get("refresh_token"):
        account.refresh_token = body["refresh_token"]
        if body.get("refresh_token_expires_in"):
            account.refresh_expires_at = add_to_date(now_datetime(), seconds=int(body["refresh_token_expires_in"]))
    if body.get("scope"):
        account.scopes = " ".join(sorted(set(body["scope"].replace(",", " ").split())))
    account.status = "Connected"


def renew_member_token(account_name):
    """Use the refresh token now. True when renewed; False when there is none or LinkedIn refused."""
    account = frappe.get_doc("LinkedIn Account", account_name)
    refresh = account.get_password("refresh_token", raise_exception=False)
    if not refresh:
        return False
    try:
        body = get_client().refresh_member_token(refresh)
    except LinkedInAPIError:
        return False
    store_member_tokens(account, body)
    account.flags.ignore_permissions = True
    account.save()
    return True


def member_token(account_name):
    """(access token, account doc) for a connected LinkedIn Account, refreshing it when it expires
    within ten minutes and a refresh token exists. Raises with a clear message otherwise."""
    account = frappe.get_doc("LinkedIn Account", account_name)
    if account.status != "Connected":
        frappe.throw(_("LinkedIn Account {0} is not connected. Open it and click Connect.").format(account_name))
    soon = add_to_date(now_datetime(), minutes=10)
    if account.expires_at and get_datetime(account.expires_at) <= soon:
        refresh = account.get_password("refresh_token", raise_exception=False)
        if not refresh:
            account.db_set("status", "Expired")
            frappe.throw(_("The LinkedIn sign-in for {0} has expired. Open the account and click Connect again.").format(account_name))
        try:
            body = get_client().refresh_member_token(refresh)
        except LinkedInAPIError as e:
            account.db_set("status", "Expired")
            frappe.throw(_("Could not renew the LinkedIn sign-in for {0}: {1}").format(account_name, api_error_text(e)))
        store_member_tokens(account, body)
        account.flags.ignore_permissions = True
        account.save()
    return account.get_password("access_token"), account

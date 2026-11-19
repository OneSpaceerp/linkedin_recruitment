# Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
# For license information, please see license.txt

"""The one redirect URL registered in the LinkedIn app. Routes the browser back to Desk (account
connection) or to the apply page (candidate sign-in)."""

from urllib.parse import quote, urlencode

import frappe
from frappe import _

from linkedin_recruitment.services import oauth


def _redirect(location):
    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = location


@frappe.whitelist(allow_guest=True, methods=["GET"])
def callback(code=None, state=None, error=None, error_description=None, **kwargs):
    data = oauth.pop_state(state)
    if not data:
        frappe.respond_as_web_page(_("LinkedIn sign-in expired"),
                                   _("This sign-in link is no longer valid. Please start again."),
                                   http_status_code=400, indicator_color="red")
        return

    if data["flow"] == "apply":
        job = data.get("job") or ""
        target = f"/linkedin-apply/{quote(job)}"
        if error or not code:
            _redirect(f"{target}?{urlencode({'error': error_description or error or 'cancelled'})}")
            return
        try:
            key = oauth.candidate_identity(code)
        except Exception as e:
            frappe.log_error(title="LinkedIn candidate sign-in")
            _redirect(f"{target}?{urlencode({'error': oauth.error_text(e)[:200]})}")
            return
        _redirect(f"{target}?{urlencode({'t': key})}")
        return

    # account flow: only the user who started it may finish it
    if frappe.session.user != data.get("user"):
        frappe.respond_as_web_page(_("Not permitted"), _("Sign in to the site as the user who started the connection."),
                                   http_status_code=403, indicator_color="red")
        return
    account = data.get("account")
    desk = f"/desk/linkedin-account/{quote(account)}" if account else "/desk/linkedin-account"
    if error or not code:
        frappe.msgprint(_("LinkedIn did not connect: {0}").format(error_description or error or _("cancelled")))
        _redirect(desk)
        return
    try:
        doc = oauth.connect_account(code, data)
        frappe.db.commit()
        desk = f"/desk/linkedin-account/{quote(doc.name)}"
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(title="LinkedIn account connection")
        frappe.respond_as_web_page(_("LinkedIn did not connect"), oauth.error_text(e), http_status_code=502,
                                   indicator_color="red")
        return
    _redirect(desk)

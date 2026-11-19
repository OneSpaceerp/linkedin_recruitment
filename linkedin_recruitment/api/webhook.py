# Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
# For license information, please see license.txt

"""Apply Connect webhook (jobApplicationWebhookUrl).

GET  ?challengeCode=...  -> {"challengeCode", "challengeResponse"} (endpoint validation, every 2 h)
POST application JSON    -> 200 {} or a delivery error LinkedIn understands

Responses are raw JSON (not wrapped in Frappe's {"message": ...}) because LinkedIn reads them.
"""

import json

import frappe
from frappe.rate_limiter import rate_limit
from werkzeug.wrappers import Response

from linkedin_recruitment.linkedin import signatures
from linkedin_recruitment.services import applicants
from linkedin_recruitment.services.settings import client_secret, get_settings


def _json(status, body):
    return Response(json.dumps(body), status=status, mimetype="application/json")


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
@rate_limit(limit=600, seconds=60)
def apply_connect(**kwargs):
    request = frappe.request
    if request.method == "GET":
        code = request.args.get("challengeCode")
        secret = client_secret(get_settings())
        if not code or not secret or len(code) > 200:
            return _json(400, {"error": "challengeCode is required"})
        return _json(200, signatures.challenge_body(code, secret))

    raw = request.get_data(cache=True) or b""
    remote_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
    try:
        status, body = applicants.receive(raw, request.headers.get("X-LI-Signature"), remote_ip)
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        frappe.log_error(title="LinkedIn Apply Connect webhook")
        status, body = 500, {"errors": [{"errorCode": "TRANSIENT_ERROR"}]}
    return _json(status, body)

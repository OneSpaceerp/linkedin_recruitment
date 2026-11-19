"""HTTP client for the LinkedIn endpoints this app uses.

Free of frappe: the caller passes credentials, an optional ``requests``-compatible session and a
``logger`` callable that receives one dict per HTTP exchange (the Frappe side writes it to
LinkedIn Sync Log). Tokens are never logged.
"""

import json
import time
from urllib.parse import quote, urlencode

from . import constants as C

RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_DOWNLOAD = 10 * 1024 * 1024
_SECRET_FIELDS = {"client_secret", "code", "refresh_token", "access_token", "id_token"}


class LinkedInAPIError(Exception):
    def __init__(self, message, status=0, code="", request_id="", body=None):
        self.status = status
        self.code = code
        self.request_id = request_id
        self.body = body
        super().__init__(message)

    @property
    def is_auth_error(self):
        return self.status == 401

    @property
    def retryable(self):
        return self.status in RETRY_STATUSES or self.status == 0


def _scrub(data):
    """Copy of a form/JSON body with secrets replaced, for the sync log."""
    if isinstance(data, dict):
        return {k: ("***" if k in _SECRET_FIELDS else _scrub(v)) for k, v in data.items()}
    if isinstance(data, list):
        return [_scrub(v) for v in data]
    return data


def _error_message(status, body, text):
    if isinstance(body, dict):
        if body.get("error_description") or body.get("error"):
            return str(body.get("error_description") or body.get("error")), str(body.get("error") or "")
        message = body.get("message") or ""
        code = str(body.get("code") or body.get("serviceErrorCode") or "")
        if message:
            return message, code
    return (text or f"HTTP {status}")[:500], ""


class LinkedInClient:
    def __init__(self, client_id, client_secret, talent_version=C.DEFAULT_TALENT_VERSION,
                 marketing_version=C.DEFAULT_MARKETING_VERSION, session=None, logger=None,
                 timeout=30, max_retries=3, sleep=time.sleep):
        self.client_id = client_id
        self.client_secret = client_secret
        self.talent_version = talent_version or C.DEFAULT_TALENT_VERSION
        self.marketing_version = marketing_version or C.DEFAULT_MARKETING_VERSION
        self._session = session
        self.logger = logger
        self.timeout = timeout
        self.max_retries = max_retries
        self.sleep = sleep

    @property
    def session(self):
        if self._session is None:
            import requests

            self._session = requests.Session()
            self._session.headers["User-Agent"] = "linkedin_recruitment (Frappe HR)"
        return self._session

    # ------------------------------------------------------------------------------ transport

    def request(self, method, url, *, token=None, json_body=None, form=None, headers=None, version=None,
                protocol_v2=False, operation="", reference=None, raw=False):
        """One call with retries for 429/5xx and connection errors. Returns (status, body, response).

        ``body`` is parsed JSON (or None); with ``raw`` the response content is not decoded.
        Raises LinkedInAPIError for any non-2xx after the retries.
        """
        url = url if url.startswith("http") else C.API_BASE + url
        hdrs = {"Accept": "application/json"}
        if token:
            hdrs["Authorization"] = f"Bearer {token}"
        if version:
            hdrs["LinkedIn-Version"] = version
        if protocol_v2:
            hdrs["X-Restli-Protocol-Version"] = "2.0.0"
        hdrs.update(headers or {})

        attempt = 0
        while True:
            attempt += 1
            started = time.monotonic()
            response, error = None, None
            try:
                response = self.session.request(
                    method, url, headers=hdrs, json=json_body, data=form, timeout=self.timeout, stream=raw
                )
            except Exception as exc:  # connection reset, DNS, timeout
                error = exc
            duration = int((time.monotonic() - started) * 1000)

            status = response.status_code if response is not None else 0
            body, text = None, ""
            if response is not None and not raw:
                text = response.text or ""
                try:
                    body = response.json() if text.strip() else None
                except ValueError:
                    body = None
            request_id = ""
            if response is not None:
                request_id = response.headers.get("x-li-uuid") or response.headers.get("x-li-request-id") or ""

            ok = response is not None and 200 <= status < 300
            message, code = ("", "")
            if not ok:
                message, code = (str(error), "") if error else _error_message(status, body, text)
            self._log(
                method=method, url=url.split("?")[0] if "accessToken" in url else url, status=status,
                duration_ms=duration, request_body=_scrub(json_body if json_body is not None else form),
                response_body=None if raw else (_scrub(body) if body is not None else text[:4000]),
                request_id=request_id, error=message, operation=operation, attempt=attempt, reference=reference,
            )
            if ok:
                return status, body, response

            retry = (error is not None or status in RETRY_STATUSES) and attempt <= self.max_retries
            if not retry:
                raise LinkedInAPIError(message or f"HTTP {status}", status=status, code=code,
                                       request_id=request_id, body=body)
            wait = 2 ** (attempt - 1)
            if response is not None and response.headers.get("Retry-After", "").isdigit():
                wait = int(response.headers["Retry-After"])
            self.sleep(min(wait, 30))

    def _log(self, **entry):
        if self.logger:
            try:
                self.logger(entry)
            except Exception:
                pass  # logging must never break the integration

    # ---------------------------------------------------------------------------------- OAuth

    def authorize_url(self, redirect_uri, scopes, state):
        params = {"response_type": "code", "client_id": self.client_id, "redirect_uri": redirect_uri,
                  "state": state, "scope": " ".join(scopes)}
        return f"{C.AUTH_URL}?{urlencode(params, quote_via=quote)}"

    def _token(self, form, operation):
        form = {**form, "client_id": self.client_id, "client_secret": self.client_secret}
        _, body, _ = self.request("POST", C.TOKEN_URL, form=form, operation=operation,
                                  headers={"Content-Type": "application/x-www-form-urlencoded"})
        if not body or not body.get("access_token"):
            raise LinkedInAPIError("LinkedIn returned no access token.", status=200, body=body)
        body["expires_in"] = int(body.get("expires_in") or 0)
        if body.get("refresh_token_expires_in") is not None:
            body["refresh_token_expires_in"] = int(body["refresh_token_expires_in"])
        return body

    def client_credentials_token(self):
        """2-legged token for the Job Posting API and Apply Connect media (30 minutes)."""
        return self._token({"grant_type": "client_credentials"}, "Client Credentials Token")

    def exchange_code(self, code, redirect_uri):
        return self._token({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri},
                           "Authorization Code Exchange")

    def refresh_member_token(self, refresh_token):
        return self._token({"grant_type": "refresh_token", "refresh_token": refresh_token}, "Refresh Member Token")

    # --------------------------------------------------------------------------------- member

    def userinfo(self, token):
        """OpenID Connect profile: sub, name, given_name, family_name, email, email_verified, picture, locale."""
        _, body, _ = self.request("GET", C.USERINFO_PATH, token=token, operation="Member Profile")
        return body or {}

    def organization_acls(self, token):
        """Organizations the member may act for: [{organization, role, state}]."""
        query = urlencode({"q": "roleAssignee", "state": "APPROVED", "count": 100})
        _, body, _ = self.request("GET", f"{C.ORG_ACLS_PATH}?{query}", token=token, version=self.marketing_version,
                                  protocol_v2=True, operation="Organization Access")
        return [
            {"organization": e.get("organization") or e.get("organizationTarget") or "", "role": e.get("role") or "",
             "state": e.get("state") or ""}
            for e in (body or {}).get("elements") or []
        ]

    def organization_name(self, token, organization_urn):
        org_id = (organization_urn or "").rsplit(":", 1)[-1]
        _, body, _ = self.request("GET", f"{C.ORGANIZATIONS_PATH}/{quote(org_id)}", token=token,
                                  version=self.marketing_version, protocol_v2=True, operation="Organization Lookup")
        return (body or {}).get("localizedName") or ""

    # ----------------------------------------------------------------------------------- jobs

    def submit_job_postings(self, token, elements, reference=None):
        _, body, _ = self.request(
            "POST", C.JOB_POSTINGS_PATH, token=token, json_body={"elements": elements}, version=self.talent_version,
            headers={"X-Restli-Method": "batch_create", "Content-Type": "application/json"},
            operation="Submit Job Postings", reference=reference,
        )
        return body or {}

    def job_posting_tasks(self, token, task_urns, reference=None):
        """Task status for up to ~40 URNs per call (the query string must stay under 4 KB)."""
        if not task_urns:
            return {"results": {}, "errors": {}}
        query = "&".join("ids=" + quote(u, safe="") for u in task_urns)
        _, body, _ = self.request("GET", f"{C.JOB_TASKS_PATH}?{query}", token=token, version=self.talent_version,
                                  operation="Job Posting Task Status", reference=reference)
        return body or {}

    # ---------------------------------------------------------------------------------- posts

    def create_post(self, token, payload, reference=None):
        """Returns the post URN from the x-restli-id header (urn:li:share:... or urn:li:ugcPost:...)."""
        _, _, response = self.request(
            "POST", C.POSTS_PATH, token=token, json_body=payload, version=self.marketing_version, protocol_v2=True,
            headers={"Content-Type": "application/json"}, operation="Create Post", reference=reference,
        )
        return response.headers.get("x-restli-id") or response.headers.get("x-linkedin-id") or ""

    def delete_post(self, token, urn, reference=None):
        self.request("DELETE", f"{C.POSTS_PATH}/{quote(urn, safe='')}", token=token, version=self.marketing_version,
                     protocol_v2=True, headers={"X-RestLi-Method": "DELETE"}, operation="Delete Post", reference=reference)

    # ---------------------------------------------------------------------------------- media

    def download(self, url, token, reference=None, max_bytes=MAX_DOWNLOAD):
        """Applicant resume or cover letter (Apply Connect mediaUrl). Returns (content, content_type)."""
        _, _, response = self.request("GET", url, token=token, raw=True, operation="Download Applicant File",
                                      reference=reference)
        chunks, size = [], 0
        for chunk in response.iter_content(64 * 1024):
            size += len(chunk)
            if size > max_bytes:
                response.close()
                raise LinkedInAPIError(f"The file is larger than {max_bytes // (1024 * 1024)} MB.", status=413)
            chunks.append(chunk)
        return b"".join(chunks), (response.headers.get("Content-Type") or "").split(";")[0].strip()


def dumps(data, limit=20000):
    """Compact JSON for logs, truncated."""
    try:
        text = json.dumps(data, ensure_ascii=False, default=str, indent=1)
    except (TypeError, ValueError):
        text = str(data)
    return text if len(text) <= limit else text[:limit] + "\n... (truncated)"

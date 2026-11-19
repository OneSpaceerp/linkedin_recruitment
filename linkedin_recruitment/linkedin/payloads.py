"""Build and read LinkedIn request/response bodies. Pure Python, no frappe.

Job postings follow the Job Posting API (``POST /rest/simpleJobPostings`` with
``X-Restli-Method: batch_create``); company page announcements follow the Posts API.
"""

import re
from datetime import UTC, datetime
from html import escape
from html.parser import HTMLParser

from . import constants as C


class PayloadError(ValueError):
    """The record cannot be sent: ``problems`` lists every reason, in plain words."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


# ------------------------------------------------------------------------------------ helpers


def normalise_key(text):
    return re.sub(r"[^a-z]", "", (text or "").lower())


def employment_status(employment_type):
    """Frappe HR Employment Type name -> LinkedIn employmentStatus (OTHER when unknown)."""
    if not employment_type:
        return "FULL_TIME"
    return C.EMPLOYMENT_TYPE_MAP.get(normalise_key(employment_type), "OTHER")


def format_location(*parts):
    """'Cairo', '', 'Egypt' -> 'Cairo, Egypt' (empty and repeated parts dropped)."""
    seen, out = set(), []
    for part in parts:
        part = (part or "").strip()
        if part and part.lower() not in seen:
            seen.add(part.lower())
            out.append(part)
    return ", ".join(out)


def epoch_ms(value=None):
    """datetime (naive = UTC) or None (now) -> milliseconds since epoch."""
    value = value or datetime.now(UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return int(value.timestamp() * 1000)


def job_id_from_urn(urn):
    """'urn:li:jobPosting:4215800322' -> '4215800322'."""
    return (urn or "").rsplit(":", 1)[-1] if urn else ""


def job_url(urn):
    job_id = job_id_from_urn(urn)
    return C.JOB_URL.format(id=job_id) if job_id else ""


# -------------------------------------------------------------------------------- description

_ALLOWED_TAGS = {"b", "strong", "i", "em", "u", "br", "p", "ul", "ol", "li"}
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_DROP_CONTENT = {"script", "style", "head", "title", "iframe", "object", "noscript", "template"}
_BLOCK = {"div", "section", "article", "blockquote", "table", "tr", "pre"}


class _Sanitiser(HTMLParser):
    """Keeps the small tag set LinkedIn renders, without attributes. Headings become bold
    paragraphs, other block elements become line breaks, everything else is unwrapped."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _DROP_CONTENT:
            self.skip += 1
        elif self.skip:
            return
        elif tag in _ALLOWED_TAGS:
            self.out.append(f"<{tag}>" if tag != "br" else "<br/>")
        elif tag in _HEADINGS:
            self.out.append("<p><b>")

    def handle_startendtag(self, tag, attrs):
        if not self.skip and tag == "br":
            self.out.append("<br/>")

    def handle_endtag(self, tag):
        if tag in _DROP_CONTENT:
            self.skip = max(0, self.skip - 1)
        elif self.skip:
            return
        elif tag in _ALLOWED_TAGS and tag != "br":
            self.out.append(f"</{tag}>")
        elif tag in _HEADINGS:
            self.out.append("</b></p>")
        elif tag in _BLOCK:
            self.out.append("<br/>")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(escape(data, quote=False))


def clean_description(html):
    """Job Opening description (Text Editor HTML) -> LinkedIn-safe HTML: no CSS, no attributes."""
    if not html:
        return ""
    parser = _Sanitiser()
    parser.feed(html)
    parser.close()
    text = "".join(parser.out)
    text = re.sub(r"(<br/>\s*){3,}", "<br/><br/>", text)
    text = re.sub(r"<p>\s*</p>", "", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"^(\s|<br/>)+|(\s|<br/>)+$", "", text)
    return text.strip()


def plain_text(html):
    """Tags removed, whitespace collapsed: used for length checks and post descriptions."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


# -------------------------------------------------------------------------------- job posting


def company_fields(company):
    """How the hiring company is identified, in LinkedIn's order of preference."""
    if company.get("integration_context"):
        return {"integrationContext": company["integration_context"]}
    if company.get("company_id"):
        return {"company": f"urn:li:company:{company['company_id']}"}
    if company.get("company_page_url"):
        return {"companyPageUrl": company["company_page_url"]}
    if company.get("company_name"):
        return {"companyName": company["company_name"]}
    return {}


def validate_job(job, company):
    """Every reason LinkedIn would reject this job, as a list of sentences (empty = ok)."""
    problems = []
    if not (job.get("external_id") or "").strip():
        problems.append("The job has no external id.")
    if not (job.get("title") or "").strip():
        problems.append("Job Title is empty.")
    length = len(job.get("description") or "")
    if len(plain_text(job.get("description"))) < C.DESCRIPTION_MIN:
        problems.append(f"The description must have at least {C.DESCRIPTION_MIN} characters of text.")
    if length > C.DESCRIPTION_MAX:
        problems.append(f"The description is {length} characters; LinkedIn accepts at most {C.DESCRIPTION_MAX}.")
    if not (job.get("location") or "").strip():
        problems.append("Set the LinkedIn location (for example 'Cairo, Egypt').")
    url = job.get("apply_url") or ""
    if not re.match(r"^https?://[^\s/$.?#].[^\s]*$", url):
        problems.append("The apply URL must be a full http(s) address.")
    if job.get("employment_status") not in C.EMPLOYMENT_STATUSES:
        problems.append(f"Unknown employment status {job.get('employment_status')!r}.")
    if job.get("experience_level") and job["experience_level"] not in C.EXPERIENCE_LEVELS:
        problems.append(f"Unknown experience level {job.get('experience_level')!r}.")
    if job.get("workplace_type") and job["workplace_type"] not in C.WORKPLACE_TYPES:
        problems.append(f"Unknown workplace type {job.get('workplace_type')!r}.")
    listing = job.get("listing_type") or "BASIC"
    if listing not in C.LISTING_TYPES:
        problems.append(f"Unknown listing type {listing!r}.")
    if listing == "PREMIUM" and not job.get("contract_urn"):
        problems.append("Promoted (PREMIUM) jobs need the LinkedIn contract URN in LinkedIn Settings.")
    if len(job.get("job_functions") or []) > 3:
        problems.append("LinkedIn accepts at most three job functions.")
    if not company_fields(company):
        problems.append("Set the LinkedIn Organization ID, integration context or company name in LinkedIn Settings.")
    if job.get("apply_connect") and not (job["apply_connect"].get("webhook_url") or "").startswith("https://"):
        problems.append("Apply Connect needs the site to be served over HTTPS (the webhook URL must start with https://).")
    return problems


def onsite_apply_configuration(webhook_url, resume_required=True, questions=None):
    """Apply Connect (LinkedIn Easy Apply into the ATS). ``questions`` overrides the default set."""
    if questions is None:
        questions = {"resumeQuestions": {"resumeQuestionRequirement": "REQUIRED" if resume_required else "OPTIONAL"}}
    return {"jobApplicationWebhookUrl": webhook_url, "questions": questions}


def job_posting_element(job, company, operation="CREATE", now=None):
    """One element of the simpleJobPostings batch. Raises PayloadError when invalid.

    ``job`` keys: external_id, title, description (clean HTML), apply_url, location,
    employment_status, workplace_type (Desk label), experience_level, listing_type,
    job_functions [codes], industries [ids], listed_at (datetime), poster_email,
    contract_urn, apply_connect {webhook_url, resume_required, questions}.
    ``company`` keys: integration_context, company_id, company_page_url, company_name.
    """
    if operation not in C.OPERATIONS:
        raise PayloadError([f"Unknown operation {operation!r}."])
    problems = validate_job(job, company)
    if problems:
        raise PayloadError(problems)

    now_ms = epoch_ms(now)
    listed = epoch_ms(job["listed_at"]) if job.get("listed_at") else now_ms
    element = {
        "externalJobPostingId": str(job["external_id"]),
        "jobPostingOperationType": operation,
        "title": job["title"].strip()[:200],
        "description": job["description"],
        "companyApplyUrl": job["apply_url"],
        "location": job["location"].strip(),
        "employmentStatus": job["employment_status"],
        "listedAt": min(listed, now_ms),  # LinkedIn rejects listedAt in the future
        "listingType": job.get("listing_type") or "BASIC",
    }
    element.update(company_fields(company))
    workplace = C.WORKPLACE_TYPES.get(job.get("workplace_type") or "On-site")
    if workplace:
        element["workplaceTypes"] = [workplace]
    if job.get("experience_level"):
        element["experienceLevel"] = job["experience_level"]
    if job.get("job_functions"):
        element["jobFunctions"] = list(job["job_functions"])[:3]
    if job.get("industries"):
        element["industries"] = [i if str(i).startswith("urn:") else f"urn:li:industry:{i}" for i in job["industries"]]
    if job.get("listing_type") == "PREMIUM":
        element["contract"] = job["contract_urn"]
    if job.get("poster_email"):
        element["posterEmail"] = job["poster_email"]
    if job.get("company_job_code"):
        element["companyJobCode"] = str(job["company_job_code"])[:75]
    apply = job.get("apply_connect")
    if apply:
        element["onsiteApplyConfiguration"] = onsite_apply_configuration(
            apply["webhook_url"], apply.get("resume_required", True), apply.get("questions")
        )
    return element


def batch_body(elements):
    if len(elements) > C.MAX_BATCH:
        raise PayloadError([f"At most {C.MAX_BATCH} jobs per call."])
    return {"elements": list(elements)}


def _error_text(error):
    if not error:
        return ""
    message = (error.get("message") or "").strip()
    code = error.get("code") or ""
    return f"{code}: {message}" if code and code not in message else message


def parse_batch_response(body):
    """simpleJobPostings response -> [{ok, task_urn, external_id, status, error}] in request order."""
    out = []
    for el in (body or {}).get("elements") or []:
        status = int(el.get("status") or 0)
        error = el.get("error") or {}
        out.append(
            {
                "ok": 200 <= status < 300 and not error,
                "task_urn": el.get("id") or "",
                "external_id": (el.get("entity") or {}).get("externalJobPostingId")
                or (error.get("errorDetails") or {}).get("externalJobPostingId")
                or "",
                "status": status,
                "error": _error_text(error),
            }
        )
    return out


def parse_task_results(body):
    """simpleJobPostingTasks response -> [{task_urn, external_id, status, job_posting_urn, location, error}]."""
    out = []
    for urn, task in ((body or {}).get("results") or {}).items():
        out.append(
            {
                "task_urn": task.get("id") or urn,
                "external_id": task.get("externalJobPostingId") or "",
                "status": task.get("status") or "",
                "job_posting_urn": task.get("jobPosting") or "",
                "location": task.get("location") or "",
                "error": (task.get("errorMessage") or "").strip(),
            }
        )
    for urn, err in ((body or {}).get("errors") or {}).items():
        out.append({"task_urn": urn, "external_id": "", "status": "FAILED", "job_posting_urn": "", "location": "",
                    "error": _error_text(err) or str(err)})
    return out


def summarise_tasks(tasks):
    """Several task results for one job (multi-location) -> one outcome.

    Returns (state, job_posting_urn, error) where state is 'pending', 'succeeded' or 'failed'.
    A job counts as live when any location succeeded; errors of the others are still reported.
    """
    if not tasks:
        return "pending", "", ""
    statuses = {t["status"] for t in tasks}
    errors = "; ".join(dict.fromkeys(t["error"] for t in tasks if t["error"]))
    urn = next((t["job_posting_urn"] for t in tasks if t["job_posting_urn"]), "")
    if "SUCCEEDED" in statuses or ("PROCESSED" in statuses and not errors):
        return "succeeded", urn, errors
    if "IN_PROGRESS" in statuses:
        return "pending", urn, errors
    return "failed", urn, errors or "LinkedIn reported the task as failed."


# -------------------------------------------------------------------------------------- posts

_LITTLE_RESERVED = re.compile(r"([\\|{}@\[\]()<>#*_~])")


def escape_little(text):
    """Escape LinkedIn 'little' text-format characters so commentary is shown literally."""
    return _LITTLE_RESERVED.sub(r"\\\1", text or "")


def hashtags(raw):
    """'hiring, #jobs, Cairo jobs' -> '#hiring #jobs #CairoJobs'.

    Commas, semicolons and new lines separate tags; words inside one tag are joined in CamelCase;
    duplicates (any case) are dropped."""
    tags = []
    for part in re.split(r"[,\n;]+", raw or ""):
        words = part.strip().lstrip("#").split()
        joined = words[0] if len(words) == 1 else "".join(w[:1].upper() + w[1:] for w in words)
        word = re.sub(r"\W", "", joined or "")
        if word and word.lower() not in {t.lower() for t in tags}:
            tags.append(word)
    return " ".join(f"#{t}" for t in tags)


def post_payload(author_urn, commentary, link=None, title=None, description=None, visibility="PUBLIC", tags=""):
    """Posts API body for an organic post, optionally with an article card linking to the job."""
    problems = []
    if not re.match(r"^urn:li:(organization|person):\w+", author_urn or ""):
        problems.append("The post author must be an organization or member URN.")
    text = escape_little((commentary or "").strip())
    if tags:
        text = f"{text}\n\n{hashtags(tags)}" if text else hashtags(tags)
    if not text:
        problems.append("The post text is empty.")
    if len(text) > C.POST_COMMENTARY_MAX:
        problems.append(f"The post text is {len(text)} characters; LinkedIn accepts at most {C.POST_COMMENTARY_MAX}.")
    if visibility not in ("PUBLIC", "CONNECTIONS", "LOGGED_IN"):
        problems.append(f"Unknown visibility {visibility!r}.")
    if link and not re.match(r"^https?://", link):
        problems.append("The link must be a full http(s) address.")
    if problems:
        raise PayloadError(problems)

    body = {
        "author": author_urn,
        "commentary": text,
        "visibility": visibility,
        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    if link:
        article = {"source": link, "title": (title or link)[:200]}
        if description:
            article["description"] = plain_text(description)[:250]
        body["content"] = {"article": article}
    return body


def post_url(urn):
    return C.POST_URL.format(urn=urn) if urn else ""

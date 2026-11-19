"""Job Opening -> LinkedIn job, through the Job Posting API.

LinkedIn processes job submissions asynchronously: a submit returns a task URN, and the task
status (polled every ten minutes, or on demand) tells whether the job went live.
"""

import re
from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import cint, get_url, now_datetime

from linkedin_recruitment.linkedin import payloads as P
from linkedin_recruitment.linkedin.client import LinkedInAPIError

from .settings import api_error_text, get_client, get_settings, require_enabled, webhook_url, with_app_token

LIVE = ("Listed", "In Progress", "Queued")
PENDING = ("Queued", "In Progress", "Closing")
SYNC_FIELDS = ("job_title", "description", "status", "employment_type", "designation", "company", "lower_range",
               "upper_range", "li_location", "li_workplace_type", "li_experience_level", "li_publish")


# --------------------------------------------------------------------------------- building


def external_id_prefix(settings):
    prefix = (settings.external_id_prefix or "").strip()
    if not prefix:
        prefix = re.sub(r"[^A-Za-z0-9]", "", (frappe.local.site or "site").split(".")[0])[:20] or "site"
    return prefix


def new_external_id(job_opening, settings, attempt=0):
    base = f"{external_id_prefix(settings)}-{job_opening}"
    return base if not attempt else f"{base}-r{attempt}"


def apply_url(job_opening, settings=None):
    """Where LinkedIn sends candidates. 'Job Opening Page' falls back to the Apply with LinkedIn
    page when the opening is not published on the website."""
    settings = settings or get_settings()
    mode = settings.apply_url_mode or "Job Opening Page"
    route = (job_opening.get("route") or "").strip("/")
    if mode == "Custom URL" and settings.custom_apply_url:
        return settings.custom_apply_url.replace("{job}", quote(job_opening.name)).replace("{route}", route)
    linkedin_page = get_url(f"/linkedin-apply/{quote(job_opening.name)}")
    if mode == "Apply with LinkedIn Page":
        return linkedin_page
    if route and cint(job_opening.get("publish")):
        return get_url(f"/{route}")
    return linkedin_page if cint(settings.enable_apply_with_linkedin) else ""


def location_for(job_opening):
    """The Job Opening's LinkedIn location, else 'Branch city, Company country', else the country."""
    if job_opening.get("li_location"):
        return job_opening.li_location
    country = frappe.db.get_value("Company", job_opening.company, "country") if job_opening.get("company") else ""
    city = ""
    if job_opening.get("location"):  # Branch name
        city = job_opening.location
    return P.format_location(city, country)


def job_functions_of(doc, field):
    return [row.job_function for row in doc.get(field) or [] if row.job_function]


def ensure_posting(job_opening_name):
    """The LinkedIn Job Posting of a Job Opening, created with defaults when missing (not saved to LinkedIn)."""
    existing = frappe.db.get_value("LinkedIn Job Posting", {"job_opening": job_opening_name})
    if existing:
        return frappe.get_doc("LinkedIn Job Posting", existing)
    settings = get_settings()
    jo = frappe.get_doc("Job Opening", job_opening_name)
    posting = frappe.new_doc("LinkedIn Job Posting")
    posting.job_opening = jo.name
    posting.external_job_id = new_external_id(jo.name, settings)
    posting.listing_type = settings.listing_type or "BASIC"
    posting.workplace_type = settings.default_workplace_type or "On-site"
    posting.experience_level = settings.default_experience_level
    posting.industries = settings.default_industries
    posting.use_apply_connect = cint(settings.enable_apply_connect)
    copy_from_job_opening(posting, jo, settings)
    posting.flags.ignore_permissions = True
    posting.insert()
    return posting


def copy_from_job_opening(posting, jo, settings=None):
    """Job Opening values win over the posting's own when they are set."""
    settings = settings or get_settings()
    posting.location = location_for(jo) or posting.location
    posting.employment_status = P.employment_status(jo.get("employment_type"))
    if jo.get("li_workplace_type"):
        posting.workplace_type = jo.li_workplace_type
    if jo.get("li_experience_level"):
        posting.experience_level = jo.li_experience_level
    functions = job_functions_of(jo, "li_job_functions")
    if functions:
        posting.set("job_functions", [{"job_function": f} for f in functions])
    posting.apply_url = apply_url(jo, settings) or posting.apply_url


def build_job(posting, settings=None):
    """(job dict, company dict) for payloads.job_posting_element."""
    settings = settings or get_settings()
    jo = frappe.get_doc("Job Opening", posting.job_opening)
    questions = None
    if settings.apply_questions_json:
        questions = frappe.parse_json(settings.apply_questions_json)
    job = {
        "external_id": posting.external_job_id,
        "title": jo.job_title or jo.designation,
        "description": P.clean_description(jo.description),
        "apply_url": posting.apply_url,
        "location": posting.location,
        "employment_status": posting.employment_status or "FULL_TIME",
        "workplace_type": posting.workplace_type or "On-site",
        "experience_level": posting.experience_level or None,
        "listing_type": posting.listing_type or "BASIC",
        "job_functions": job_functions_of(posting, "job_functions"),
        "industries": [i.strip() for i in (posting.industries or "").split(",") if i.strip()],
        "listed_at": posting.listed_on or None,
        "poster_email": settings.poster_email,
        "contract_urn": settings.contract_urn,
        "company_job_code": jo.name,
        "apply_connect": {"webhook_url": webhook_url(), "resume_required": cint(settings.resume_required),
                          "questions": questions} if cint(posting.use_apply_connect) else None,
    }
    company = {
        "integration_context": settings.integration_context,
        "company_id": settings.organization_id,
        "company_page_url": settings.company_page_url,
        "company_name": settings.company_name or jo.company,
    }
    return job, company


def preview(posting):
    """(element or None, problems) without calling LinkedIn."""
    job, company = build_job(posting)
    problems = P.validate_job(job, company)
    if problems:
        return None, problems
    return P.job_posting_element(job, company, next_operation(posting)), []


def next_operation(posting):
    if posting.status == "Listed" or (posting.status in ("In Progress", "Queued") and posting.linkedin_job_urn):
        return "UPDATE"
    return "CREATE"


# ------------------------------------------------------------------------------- operations


def _fail(posting, message):
    posting.status = "Failed"
    posting.error_message = message[:2000]
    posting.task_urns = ""
    posting.flags.ignore_permissions = True
    posting.save()
    _mirror(posting)


def submit(posting_name, operation=None):
    """Send CREATE / UPDATE / CLOSE / RENEW for one posting. Records the outcome on the posting
    and returns it; LinkedIn errors are stored, not raised."""
    settings = require_enabled("enable_job_posting_api")
    posting = frappe.get_doc("LinkedIn Job Posting", posting_name)
    jo_status = frappe.db.get_value("Job Opening", posting.job_opening, "status")
    operation = operation or next_operation(posting)

    if operation == "CREATE" and posting.status == "Closed":
        # a closed LinkedIn job cannot be created again under the same id
        match = re.search(r"-r(\d+)$", posting.external_job_id or "")
        attempt = int(match.group(1)) + 1 if match else 1
        posting.external_job_id = new_external_id(posting.job_opening, settings, attempt)
        posting.linkedin_job_urn = posting.linkedin_job_url = ""
        posting.listed_on = posting.closed_on = None
    if operation != "CLOSE" and jo_status != "Open":
        _fail(posting, _("The Job Opening is not open."))
        return posting

    copy_from_job_opening(posting, frappe.get_doc("Job Opening", posting.job_opening), settings)
    job, company = build_job(posting, settings)
    try:
        element = P.job_posting_element(job, company, operation)
    except P.PayloadError as e:
        _fail(posting, "\n".join(e.problems))
        return posting

    reference = ("LinkedIn Job Posting", posting.name)
    try:
        body = with_app_token(lambda token: get_client(settings).submit_job_postings(token, [element], reference))
    except LinkedInAPIError as e:
        _fail(posting, api_error_text(e))
        return posting

    result = (P.parse_batch_response(body) or [{"ok": False, "error": _("LinkedIn returned an empty response.")}])[0]
    if not result["ok"]:
        _fail(posting, result["error"] or _("LinkedIn rejected the job (status {0}).").format(result.get("status")))
        return posting

    posting.task_urns = result["task_urn"]
    posting.last_operation = operation
    posting.last_submitted_on = now_datetime()
    posting.status = "Closing" if operation == "CLOSE" else "In Progress"
    posting.error_message = ""
    posting.flags.ignore_permissions = True
    posting.save()
    _mirror(posting)
    return posting


def refresh(posting_names=None):
    """Read task status for postings waiting on LinkedIn (all of them when no names are given)."""
    if not posting_names:
        posting_names = frappe.get_all("LinkedIn Job Posting",
                                       filters={"status": ["in", PENDING], "task_urns": ["is", "set"]}, pluck="name")
    if not posting_names:
        return 0
    settings = get_settings()
    if not (cint(settings.enabled) and cint(settings.enable_job_posting_api)):
        return 0
    postings = {n: frappe.get_doc("LinkedIn Job Posting", n) for n in posting_names}
    by_urn = {}
    for posting in postings.values():
        for urn in (posting.task_urns or "").split():
            by_urn[urn] = posting.name

    urns, done = list(by_urn), 0
    for start in range(0, len(urns), 20):
        chunk = urns[start:start + 20]
        try:
            body = with_app_token(lambda token, c=chunk: get_client(settings).job_posting_tasks(token, c))
        except LinkedInAPIError as e:
            frappe.log_error(title="LinkedIn task status", message=api_error_text(e))
            continue
        tasks_by_posting = {}
        for task in P.parse_task_results(body):
            parent = task["task_urn"]
            owner = by_urn.get(parent) or next((p for u, p in by_urn.items() if parent.startswith(u)), None)
            if owner:
                tasks_by_posting.setdefault(owner, []).append(task)
        for name, tasks in tasks_by_posting.items():
            done += apply_task_results(postings[name], tasks)
    return done


def apply_task_results(posting, tasks):
    state, urn, error = P.summarise_tasks(tasks)
    if state == "pending":
        return 0
    closing = posting.last_operation == "CLOSE"
    if state == "succeeded":
        if closing:
            posting.status, posting.closed_on = "Closed", now_datetime()
        else:
            posting.status = "Listed"
            posting.listed_on = posting.listed_on or now_datetime()
            if urn:
                posting.linkedin_job_urn = urn
                posting.linkedin_job_url = P.job_url(urn)
        posting.error_message = error[:2000] if error else ""
    else:
        # a failed CLOSE leaves the job live on LinkedIn
        posting.status = "Listed" if closing and posting.linkedin_job_urn else "Failed"
        posting.error_message = (error or _("LinkedIn reported the task as failed."))[:2000]
    posting.task_urns = ""
    posting.flags.ignore_permissions = True
    posting.save()
    _mirror(posting)
    return 1


def _mirror(posting):
    """Show the LinkedIn state on the Job Opening (custom fields, no modified bump)."""
    if frappe.get_meta("Job Opening").has_field("li_status"):
        frappe.db.set_value("Job Opening", posting.job_opening,
                            {"li_job_posting": posting.name, "li_status": posting.status,
                             "li_job_url": posting.linkedin_job_url or ""}, update_modified=False)


def publish(job_opening_name):
    posting = ensure_posting(job_opening_name)
    return submit(posting.name)


def close(job_opening_name):
    name = frappe.db.get_value("LinkedIn Job Posting", {"job_opening": job_opening_name})
    if not name:
        return None
    status = frappe.db.get_value("LinkedIn Job Posting", name, "status")
    if status not in LIVE and status != "Failed":
        return frappe.get_doc("LinkedIn Job Posting", name)
    return submit(name, "CLOSE")


# ----------------------------------------------------------------------------- doc events


def on_job_opening_update(doc, method=None):
    settings = get_settings()
    if not cint(settings.enabled):
        return
    posting = frappe.db.get_value("LinkedIn Job Posting", {"job_opening": doc.name}, ["name", "status"], as_dict=True)

    if cint(settings.enable_job_posting_api) and cint(settings.auto_publish):
        if doc.status == "Open" and cint(doc.get("li_publish")):
            if not posting or posting.status in ("Draft", "Failed", "Closed") or _relevant_change(doc):
                _enqueue("publish", doc.name)
        elif posting and posting.status in LIVE and (doc.status != "Open" or not cint(doc.get("li_publish"))):
            if cint(settings.close_with_job_opening):
                _enqueue("close", doc.name)

    if (cint(settings.enable_company_posts) and cint(settings.auto_post) and doc.status == "Open"
            and cint(doc.get("li_announce"))
            and not frappe.db.exists("LinkedIn Post", {"job_opening": doc.name, "status": ["!=", "Failed"]})):
        frappe.enqueue("linkedin_recruitment.services.posts.announce_job_opening", queue="default",
                       job_opening_name=doc.name, enqueue_after_commit=True,
                       job_id=f"linkedin-post-{doc.name}", deduplicate=True)


def _relevant_change(doc):
    """A field LinkedIn shows changed in this save (child-table rows are compared by value)."""
    before = doc.get_doc_before_save()
    if not before:
        return True
    if any(before.get(f) != doc.get(f) for f in SYNC_FIELDS if doc.meta.has_field(f)):
        return True
    return job_functions_of(before, "li_job_functions") != job_functions_of(doc, "li_job_functions")


def on_job_opening_trash(doc, method=None):
    settings = get_settings()
    if cint(settings.enabled) and cint(settings.enable_job_posting_api):
        posting = frappe.db.get_value("LinkedIn Job Posting", {"job_opening": doc.name}, "status")
        if posting in LIVE:
            close(doc.name)


def _enqueue(action, job_opening_name):
    frappe.enqueue(f"linkedin_recruitment.services.jobs.run_{action}", queue="default",
                   job_opening_name=job_opening_name, enqueue_after_commit=True,
                   job_id=f"linkedin-job-{job_opening_name}", deduplicate=True)


def run_publish(job_opening_name):
    publish(job_opening_name)


def run_close(job_opening_name):
    close(job_opening_name)


# --------------------------------------------------------------------------------- schedule


def close_orphans():
    """Close LinkedIn jobs whose Job Opening was closed without a save (e.g. Frappe HR's expiry job)."""
    settings = get_settings()
    if not (cint(settings.enabled) and cint(settings.enable_job_posting_api) and cint(settings.close_with_job_opening)):
        return 0
    rows = frappe.db.sql(
        """select p.job_opening from `tabLinkedIn Job Posting` p
           join `tabJob Opening` j on j.name = p.job_opening
           where p.status = 'Listed' and j.status != 'Open'""",
        pluck=True,
    )
    for job_opening in rows:
        close(job_opening)
        frappe.db.commit()
    return len(rows)


def count_applicants(posting_name):
    count = frappe.db.count("LinkedIn Applicant", {"linkedin_job_posting": posting_name})
    frappe.db.set_value("LinkedIn Job Posting", posting_name, "applicants", count, update_modified=False)

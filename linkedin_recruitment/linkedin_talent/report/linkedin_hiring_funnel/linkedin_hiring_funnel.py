# Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
# For license information, please see license.txt

"""Per Job Opening: LinkedIn job state, applicants from LinkedIn, and how far they got in Frappe HR."""

import frappe
from frappe import _

STAGES = ("Open", "Replied", "Hold", "Accepted", "Rejected")


def execute(filters=None):
    filters = frappe._dict(filters or {})
    return columns(), data(filters)


def columns():
    cols = [
        {"fieldname": "job_opening", "label": _("Job Opening"), "fieldtype": "Link", "options": "Job Opening", "width": 180},
        {"fieldname": "job_title", "label": _("Job Title"), "fieldtype": "Data", "width": 180},
        {"fieldname": "linkedin_status", "label": _("LinkedIn Job"), "fieldtype": "Data", "width": 110},
        {"fieldname": "posts", "label": _("Posts"), "fieldtype": "Int", "width": 70},
        {"fieldname": "applicants", "label": _("From LinkedIn"), "fieldtype": "Int", "width": 110},
        {"fieldname": "apply_connect", "label": _("Easy Apply"), "fieldtype": "Int", "width": 95},
        {"fieldname": "apply_page", "label": _("Apply Page"), "fieldtype": "Int", "width": 95},
        {"fieldname": "imported_file", "label": _("Imported"), "fieldtype": "Int", "width": 90},
    ]
    cols += [{"fieldname": scrub(s), "label": _(s), "fieldtype": "Int", "width": 85} for s in STAGES]
    cols.append({"fieldname": "acceptance_rate", "label": _("Accepted %"), "fieldtype": "Percent", "width": 100})
    return cols


def scrub(stage):
    return f"stage_{stage.lower()}"


def data(filters):
    conditions, values = ["1=1"], {}
    if filters.get("company"):
        conditions.append("jo.company = %(company)s")
        values["company"] = filters.company
    if filters.get("job_opening"):
        conditions.append("jo.name = %(job_opening)s")
        values["job_opening"] = filters.job_opening
    if filters.get("from_date"):
        conditions.append("la.creation >= %(from_date)s")
        values["from_date"] = filters.from_date
    if filters.get("to_date"):
        conditions.append("la.creation < date_add(%(to_date)s, interval 1 day)")
        values["to_date"] = filters.to_date
    where = " and ".join(conditions)

    rows = frappe.db.sql(
        f"""
        select jo.name as job_opening, jo.job_title,
            count(la.name) as applicants,
            sum(la.source = 'Apply Connect') as apply_connect,
            sum(la.source = 'Apply with LinkedIn') as apply_page,
            sum(la.source = 'File Import') as imported_file,
            {", ".join(f"sum(ja.status = '{s}') as {scrub(s)}" for s in STAGES)}
        from `tabLinkedIn Applicant` la
        join `tabJob Opening` jo on jo.name = la.job_opening
        left join `tabJob Applicant` ja on ja.name = la.job_applicant
        where {where}
        group by jo.name, jo.job_title
        order by count(la.name) desc
        """,
        values,
        as_dict=True,
    )
    if not rows:
        return []
    names = [r.job_opening for r in rows]
    status = dict(frappe.get_all("LinkedIn Job Posting", filters={"job_opening": ["in", names]},
                                 fields=["job_opening", "status"], as_list=True))
    posts = dict(frappe.db.sql(
        """select job_opening, count(*) from `tabLinkedIn Post`
           where status = 'Published' and job_opening in %(names)s group by job_opening""",
        {"names": names},
    ))
    for r in rows:
        r.linkedin_status = status.get(r.job_opening) or _("Not posted")
        r.posts = posts.get(r.job_opening) or 0
        for key in ("apply_connect", "apply_page", "imported_file", *(scrub(s) for s in STAGES)):
            r[key] = int(r.get(key) or 0)
        r.acceptance_rate = round(100.0 * r[scrub("Accepted")] / r.applicants, 1) if r.applicants else 0
    return rows

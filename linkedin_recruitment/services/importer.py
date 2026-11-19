"""LinkedIn Applicant Import: a CSV exported from LinkedIn -> LinkedIn Applicants (+ Job Applicants)."""

import frappe
from frappe import _
from frappe.utils import cint

from linkedin_recruitment.linkedin import csv_import

from .applicants import make_job_applicant
from .settings import get_settings


def file_content(file_url):
    file_doc = frappe.get_doc("File", {"file_url": file_url})
    return file_doc.get_content()


def run(import_name):
    doc = frappe.get_doc("LinkedIn Applicant Import", import_name)
    doc.db_set("status", "In Progress")
    frappe.db.commit()
    settings = get_settings()
    log = []
    imported = duplicates = errors = 0
    try:
        rows, problems = csv_import.parse_rows(file_content(doc.import_file))
    except Exception as e:
        doc.db_set({"status": "Failed", "log": _("The file could not be read: {0}").format(e)})
        return doc
    log += problems

    for row in rows:
        try:
            existing = frappe.db.get_value("LinkedIn Applicant", {"email": row["email"], "job_opening": doc.job_opening})
            if existing:
                duplicates += 1
                log.append(_("Row {0}: {1} is already an applicant ({2}).").format(row["row"], row["email"], existing))
                continue
            applicant = frappe.get_doc({
                "doctype": "LinkedIn Applicant",
                "applicant_name": row.get("applicant_name"),
                "first_name": row.get("first_name"),
                "last_name": row.get("last_name"),
                "email": row["email"],
                "phone": row.get("phone"),
                "location": row.get("location"),
                "profile_url": row.get("profile_url"),
                "headline": " at ".join(p for p in (row.get("headline"), row.get("company")) if p),
                "source": "File Import",
                "job_opening": doc.job_opening,
                "cover_letter": row.get("notes"),
            })
            applicant.flags.ignore_permissions = True
            applicant.insert()
            if cint(doc.create_job_applicants):
                make_job_applicant(applicant, settings)
            imported += 1
            frappe.db.commit()
        except Exception as e:
            frappe.db.rollback()
            errors += 1
            log.append(_("Row {0}: {1}").format(row.get("row"), e))

    skipped = len(problems) + errors
    status = "Completed" if not skipped else "Completed with Errors"
    doc.db_set({
        "status": status if (rows or not problems) else "Failed",
        "total_rows": len(rows) + len(problems),
        "imported": imported,
        "duplicates": duplicates,
        "skipped": skipped,
        "log": "\n".join(log) or _("All rows imported."),
    })
    return doc

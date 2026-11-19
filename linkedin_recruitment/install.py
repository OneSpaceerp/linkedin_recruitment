# Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
# For license information, please see license.txt

"""Install and migrate hooks. Every step is idempotent and runs again on each migrate."""

import json
import os

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

# Roles this app introduces: role name -> description
ROLES = {
    "LinkedIn Manager": "Configures the LinkedIn integration, connects LinkedIn accounts and reads sync logs.",
}

# Custom fields on standard doctypes are namespaced with this prefix
PREFIX = "li_"

EXPERIENCE = "\nENTRY_LEVEL\nASSOCIATE\nMID_SENIOR_LEVEL\nDIRECTOR\nEXECUTIVE\nINTERNSHIP\nNOT_APPLICABLE"


# ---------------------------------------------------------------------------------- hooks


def before_install():
    """Runs before anything of this app is saved (also before every migrate).

    Roles must exist before DocType permissions that name them are synced, and the 'LinkedIn'
    Job Applicant Source before Frappe's post-install `init_singles` saves LinkedIn Settings,
    whose Job Applicant Source field defaults to it (a missing link aborts the install).
    """
    for role, description in ROLES.items():
        if not frappe.db.exists("Role", role):
            frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1, "description": description}).insert(
                ignore_permissions=True
            )
    seed_applicant_source()


def after_install():
    after_migrate()


def after_migrate():
    before_install()
    make_custom_fields()
    seed_job_functions()
    seed_applicant_source()
    settings_defaults()


def before_uninstall():
    """Remove the custom fields this app added; the app's own DocTypes go with the app."""
    for dt, fields in custom_fields().items():
        for field in fields:
            name = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": field["fieldname"]})
            if name:
                frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)


# ---------------------------------------------------------------------------------- fields


def _last_field(doctype):
    """The doctype's own last field, so an added Tab/Section never captures standard fields."""
    meta = frappe.get_meta(doctype)
    own = [f.fieldname for f in meta.fields if not (f.fieldname or "").startswith(PREFIX)]
    return own[-1] if own else None


def custom_fields():
    opening = [
        {"fieldname": f"{PREFIX}tab", "fieldtype": "Tab Break", "label": "LinkedIn",
         "insert_after": _last_field("Job Opening")},
        {"fieldname": f"{PREFIX}publish", "fieldtype": "Check", "label": "Publish on LinkedIn",
         "insert_after": f"{PREFIX}tab",
         "description": "Publish this opening as a LinkedIn job (Job Posting API) while it is Open."},
        {"fieldname": f"{PREFIX}announce", "fieldtype": "Check", "label": "Announce on LinkedIn",
         "insert_after": f"{PREFIX}publish",
         "description": "Post about this opening on the company page when it opens."},
        {"fieldname": f"{PREFIX}location", "fieldtype": "Data", "label": "LinkedIn Location",
         "insert_after": f"{PREFIX}announce",
         "description": "'City, Country' as LinkedIn should show it. Empty: branch and company country."},
        {"fieldname": f"{PREFIX}workplace_type", "fieldtype": "Select", "label": "Workplace Type",
         "options": "\nOn-site\nHybrid\nRemote", "insert_after": f"{PREFIX}location"},
        {"fieldname": f"{PREFIX}experience_level", "fieldtype": "Select", "label": "Experience Level",
         "options": EXPERIENCE, "insert_after": f"{PREFIX}workplace_type"},
        {"fieldname": f"{PREFIX}job_functions", "fieldtype": "Table MultiSelect", "label": "LinkedIn Job Functions",
         "options": "LinkedIn Job Function Item", "insert_after": f"{PREFIX}experience_level",
         "description": "Up to three."},
        {"fieldname": f"{PREFIX}column", "fieldtype": "Column Break", "insert_after": f"{PREFIX}job_functions"},
        {"fieldname": f"{PREFIX}status", "fieldtype": "Data", "label": "LinkedIn Status", "read_only": 1,
         "no_copy": 1, "insert_after": f"{PREFIX}column", "in_standard_filter": 1},
        {"fieldname": f"{PREFIX}job_posting", "fieldtype": "Link", "label": "LinkedIn Job Posting",
         "options": "LinkedIn Job Posting", "read_only": 1, "no_copy": 1, "insert_after": f"{PREFIX}status"},
        {"fieldname": f"{PREFIX}job_url", "fieldtype": "Data", "label": "LinkedIn Job", "options": "URL",
         "read_only": 1, "no_copy": 1, "insert_after": f"{PREFIX}job_posting"},
    ]
    applicant = [
        {"fieldname": f"{PREFIX}section", "fieldtype": "Section Break", "label": "LinkedIn", "collapsible": 1,
         "insert_after": _last_field("Job Applicant")},
        {"fieldname": f"{PREFIX}profile_url", "fieldtype": "Data", "label": "LinkedIn Profile", "options": "URL",
         "insert_after": f"{PREFIX}section"},
        {"fieldname": f"{PREFIX}column", "fieldtype": "Column Break", "insert_after": f"{PREFIX}profile_url"},
        {"fieldname": f"{PREFIX}applicant", "fieldtype": "Link", "label": "LinkedIn Applicant",
         "options": "LinkedIn Applicant", "read_only": 1, "no_copy": 1, "insert_after": f"{PREFIX}column"},
        {"fieldname": f"{PREFIX}application_id", "fieldtype": "Data", "label": "LinkedIn Application ID",
         "read_only": 1, "no_copy": 1, "insert_after": f"{PREFIX}applicant"},
    ]
    return {"Job Opening": opening, "Job Applicant": applicant}


def make_custom_fields():
    fields = custom_fields()
    if fields:
        create_custom_fields(fields, ignore_validate=True, update=True)


# ----------------------------------------------------------------------------------- seeds


def seed_job_functions():
    path = os.path.join(os.path.dirname(__file__), "data", "job_functions.json")
    with open(path, encoding="utf-8") as fh:
        rows = json.load(fh)
    for row in rows:
        if not frappe.db.exists("LinkedIn Job Function", row["code"]):
            frappe.get_doc({"doctype": "LinkedIn Job Function", **row}).insert(ignore_permissions=True)


def seed_applicant_source():
    if frappe.db.table_exists("Job Applicant Source") and not frappe.db.exists("Job Applicant Source", "LinkedIn"):
        frappe.get_doc({"doctype": "Job Applicant Source", "source_name": "LinkedIn"}).insert(
            ignore_permissions=True, ignore_if_duplicate=True
        )


def settings_defaults():
    """Write defaults for settings never saved (Single doctypes get no defaults on migrate).
    A value someone saved, even 0 or empty, is left alone."""
    meta = frappe.get_meta("LinkedIn Settings")
    stored = set(frappe.db.sql_list("select field from `tabSingles` where doctype = 'LinkedIn Settings'"))
    for field in meta.fields:
        if field.default and not field.is_virtual and field.fieldname not in stored:
            frappe.db.set_single_value("LinkedIn Settings", field.fieldname, field.default)
    frappe.clear_document_cache("LinkedIn Settings", "LinkedIn Settings")

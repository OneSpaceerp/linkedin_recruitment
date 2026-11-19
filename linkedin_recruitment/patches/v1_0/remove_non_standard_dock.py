# Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
# For license information, please see license.txt

"""The first release shipped its Dock as "LinkedIn Recruitment" without `standard: 1`, so Frappe stored it as
the site's arrangement layer and the app had no base dock: no app rail beside the sidebar. The
fixed record is the standard dock "linkedin_recruitment"; this removes the stray site layer."""

import frappe


def execute():
    if frappe.db.exists("Dock", {"name": "LinkedIn Recruitment", "app": "linkedin_recruitment", "standard": 0}):
        frappe.delete_doc("Dock", "LinkedIn Recruitment", ignore_permissions=True, force=True)
    frappe.clear_cache()

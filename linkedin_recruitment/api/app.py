# Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
# For license information, please see license.txt

import frappe

APP_ROLES = {"System Manager", "LinkedIn Manager", "HR Manager", "HR User"}


def check_app_permission():
    """Whether the app tile shows on /desk for the current user: recruiters and LinkedIn admins."""
    if frappe.session.user == "Administrator":
        return True
    return bool(APP_ROLES & set(frappe.get_roles()))

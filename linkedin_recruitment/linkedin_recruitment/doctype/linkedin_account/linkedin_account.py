# Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class LinkedInAccount(Document):
    def validate(self):
        urn = (self.default_organization or "").strip()
        if urn and urn.isdigit():
            urn = f"urn:li:organization:{urn}"
        if urn and not urn.startswith("urn:li:organization:"):
            frappe.throw(_("Default Organization must look like urn:li:organization:12345678."))
        self.default_organization = urn

    def on_trash(self):
        if frappe.db.get_single_value("LinkedIn Settings", "post_account") == self.name:
            frappe.throw(_("This account is used for company posts in LinkedIn Settings. Choose another account there first."))

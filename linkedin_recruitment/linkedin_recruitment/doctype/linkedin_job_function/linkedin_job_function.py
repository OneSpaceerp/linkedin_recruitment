# Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class LinkedInJobFunction(Document):
    def validate(self):
        self.code = (self.code or "").strip().lower()
        if not self.code.isalnum():
            frappe.throw(_("The code is the short LinkedIn job function code, letters only (e.g. eng)."))

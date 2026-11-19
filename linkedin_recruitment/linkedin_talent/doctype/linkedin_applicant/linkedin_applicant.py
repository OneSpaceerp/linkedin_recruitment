# Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import validate_email_address


class LinkedInApplicant(Document):
    def validate(self):
        self.email = (self.email or "").strip().lower()
        if not validate_email_address(self.email):
            frappe.throw(_("{0} is not a valid email address.").format(self.email))
        if not self.applicant_name:
            self.applicant_name = " ".join(p for p in (self.first_name, self.last_name) if p) or self.email
        if self.profile_url and not self.profile_url.startswith(("http://", "https://")):
            self.profile_url = "https://" + self.profile_url.lstrip("/")

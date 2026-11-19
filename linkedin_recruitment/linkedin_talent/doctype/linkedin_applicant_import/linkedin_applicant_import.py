# Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class LinkedInApplicantImport(Document):
    def validate(self):
        if self.import_file and not self.import_file.lower().endswith((".csv", ".txt")):
            frappe.throw(_("Upload the LinkedIn export as a CSV file."))
        if self.has_value_changed("import_file") and not self.is_new():
            self.status = "Draft"

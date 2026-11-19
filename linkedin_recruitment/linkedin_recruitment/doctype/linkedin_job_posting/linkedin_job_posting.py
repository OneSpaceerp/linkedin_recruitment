# Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from linkedin_recruitment.linkedin import constants as C


class LinkedInJobPosting(Document):
    def before_insert(self):
        if not self.external_job_id:
            from linkedin_recruitment.services.jobs import new_external_id

            self.external_job_id = new_external_id(self.job_opening, frappe.get_cached_doc("LinkedIn Settings"))

    def validate(self):
        if len(self.job_functions or []) > 3:
            frappe.throw(_("LinkedIn accepts at most three job functions."))
        if self.industries:
            codes = [c.strip() for c in self.industries.replace(";", ",").split(",") if c.strip()]
            bad = [c for c in codes if not c.removeprefix("urn:li:industry:").isdigit()]
            if bad:
                frappe.throw(_("Industry codes are numbers, e.g. 4 or 96. Not valid: {0}").format(", ".join(bad)))
            self.industries = ", ".join(codes)
        if self.workplace_type == "Remote" and self.location and "," in self.location:
            frappe.msgprint(_("For remote jobs LinkedIn expects only the country as location."), indicator="orange",
                            alert=True)
        if self.employment_status and self.employment_status not in C.EMPLOYMENT_STATUSES:
            frappe.throw(_("Unknown employment status {0}.").format(self.employment_status))

    def on_trash(self):
        if self.status in ("Listed", "In Progress", "Queued", "Closing"):
            frappe.throw(_("Close the job on LinkedIn before deleting this record."))

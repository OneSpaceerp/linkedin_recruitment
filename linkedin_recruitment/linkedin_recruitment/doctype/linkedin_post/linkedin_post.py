# Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from linkedin_recruitment.linkedin import constants as C


class LinkedInPost(Document):
    def validate(self):
        if len(self.commentary or "") > C.POST_COMMENTARY_MAX:
            frappe.throw(_("LinkedIn posts can have at most {0} characters.").format(C.POST_COMMENTARY_MAX))
        if self.organization_urn and not self.organization_urn.startswith("urn:li:organization:"):
            if self.organization_urn.isdigit():
                self.organization_urn = f"urn:li:organization:{self.organization_urn}"
            else:
                frappe.throw(_("Organization URN must look like urn:li:organization:12345678."))
        if self.status == "Published" and not self.is_new():
            before = self.get_doc_before_save()
            if before and before.status == "Published" and (
                before.commentary != self.commentary or before.link_url != self.link_url
            ):
                frappe.throw(_("A published post cannot be edited here. Delete it from LinkedIn and post again."))

    def on_trash(self):
        if self.status == "Published":
            frappe.throw(_("Delete the post from LinkedIn first (Actions > Delete from LinkedIn)."))

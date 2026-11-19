# Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from linkedin_recruitment.services.settings import APP_TOKEN_KEY, redirect_uri, webhook_url


class LinkedInSettings(Document):
    @property
    def redirect_uri(self):
        return redirect_uri()

    @property
    def webhook_url(self):
        return webhook_url()

    def validate(self):
        for field in ("talent_api_version", "marketing_api_version"):
            value = (self.get(field) or "").strip()
            if value and not re.fullmatch(r"20\d{2}(0[1-9]|1[0-2])(\.\d{2})?", value):
                frappe.throw(_("{0} must be a year and month like 202604.").format(_(self.meta.get_label(field))))
        self.organization_id = (self.organization_id or "").strip()
        if self.organization_id:
            match = re.search(r"(\d+)\D*$", self.organization_id)
            if not match:
                frappe.throw(_("The LinkedIn Organization ID is the number of your company page, e.g. 12345678."))
            self.organization_id = match.group(1)
        if self.external_id_prefix:
            self.external_id_prefix = re.sub(r"[^A-Za-z0-9_-]", "", self.external_id_prefix)[:30]
        if self.apply_questions_json:
            try:
                questions = frappe.parse_json(self.apply_questions_json)
            except ValueError:
                questions = None
            if not isinstance(questions, dict):
                frappe.throw(_("Question Set (JSON) must be a JSON object."))
        if cint(self.log_retention_days) < 1:
            self.log_retention_days = 90
        if cint(self.webhook_retention_days) < 1:
            self.webhook_retention_days = 180
        if cint(self.enable_company_posts) and self.post_account:
            if not frappe.db.exists("LinkedIn Account", self.post_account):
                frappe.throw(_("LinkedIn Account {0} does not exist.").format(self.post_account))

    def on_update(self):
        # new credentials invalidate the cached application token
        if self.has_value_changed("client_id"):
            frappe.cache.delete_value(APP_TOKEN_KEY)
        if self.applicant_source and not frappe.db.exists("Job Applicant Source", self.applicant_source):
            frappe.get_doc({"doctype": "Job Applicant Source", "source_name": self.applicant_source}).insert(
                ignore_permissions=True
            )

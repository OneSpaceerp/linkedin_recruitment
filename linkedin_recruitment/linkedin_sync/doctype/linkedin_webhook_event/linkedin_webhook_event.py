# Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class LinkedInWebhookEvent(Document):
    """An Apply Connect push from LinkedIn, kept for deduplication, retries and audit."""

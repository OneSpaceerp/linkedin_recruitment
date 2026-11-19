"""Frappe side of the integration: settings, tokens, jobs, posts, applicants and imports.

Every function here may run in a background job, so none of them relies on the request.
Permission checks live in ``linkedin_recruitment.api``; services act with ignore_permissions.
"""

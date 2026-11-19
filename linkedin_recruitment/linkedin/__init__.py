"""LinkedIn protocol layer: payload builders, webhook signatures, applicant parsing and the HTTP client.

Nothing in this package imports frappe, so all of it is unit-tested without a bench
(``python -m unittest discover -s linkedin_recruitment/tests -t .``). The Frappe side lives in
``linkedin_recruitment.services``.
"""

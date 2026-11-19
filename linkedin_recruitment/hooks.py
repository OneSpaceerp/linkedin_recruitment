app_name = "linkedin_recruitment"
app_title = "LinkedIn Recruitment"
app_publisher = "nsdLabs - Nest Software Development"
app_description = "Connects Frappe HR recruitment to LinkedIn: publish Job Openings as LinkedIn jobs and company posts, receive Easy Apply applicants as Job Applicants, and let candidates apply with their LinkedIn profile"
app_email = "info@nsd-eg.com"
app_license = "GNU General Public License (v3)"

required_apps = ["frappe/erpnext", "frappe/hrms"]

app_logo_url = "/assets/linkedin_recruitment/images/linkedin-erpnext-logo.png"
app_home = "/desk/linkedin-recruitment"

# The app grid tile opens the LinkedIn Recruitment desk
add_to_apps_screen = [
    {
        "name": "linkedin_recruitment",
        "logo": "/assets/linkedin_recruitment/images/linkedin-erpnext-logo.png",
        "title": "LinkedIn Recruitment",
        "route": app_home,
        "has_permission": "linkedin_recruitment.api.app.check_app_permission",
    }
]

# Frappe v16 dock and sidebar-header icons (each module as -duotone for sidebar headers and -soft for the dock)
app_include_icons = ["/assets/linkedin_recruitment/icons/module-icons.svg"]

# Installation
# ------------
before_install = "linkedin_recruitment.install.before_install"
after_install = "linkedin_recruitment.install.after_install"
before_migrate = "linkedin_recruitment.install.before_install"
after_migrate = "linkedin_recruitment.install.after_migrate"
before_uninstall = "linkedin_recruitment.install.before_uninstall"

# Job Opening and Job Applicant stay standard Frappe HR doctypes: this app only adds a LinkedIn
# tab (custom fields from install.py) and reacts to their events.

# Apply with LinkedIn: /linkedin-apply/<job opening> is served by www/linkedin_apply.py
website_route_rules = [
    {"from_route": "/linkedin-apply/<job>", "to_route": "linkedin-apply"},
]

doctype_js = {
    "Job Opening": "public/js/job_opening.js",
    "Job Applicant": "public/js/job_applicant.js",
}

# Document Events
# ---------------
doc_events = {
    "Job Opening": {
        "on_update": "linkedin_recruitment.services.jobs.on_job_opening_update",
        "on_trash": "linkedin_recruitment.services.jobs.on_job_opening_trash",
    },
}

# Scheduled Tasks
# ---------------
scheduler_events = {
    "cron": {
        "*/10 * * * *": ["linkedin_recruitment.tasks.poll_job_tasks"],
    },
    "hourly": ["linkedin_recruitment.tasks.retry_applications"],
    "daily": [
        "linkedin_recruitment.tasks.close_closed_openings",
        "linkedin_recruitment.tasks.check_account_tokens",
        "linkedin_recruitment.tasks.purge_old_records",
    ],
}

# Testing
# -------
before_tests = "linkedin_recruitment.install.after_install"

# Personal data: applicants who ask to be forgotten are removed with their LinkedIn records
user_data_fields = [
    {"doctype": "LinkedIn Applicant", "filter_by": "email", "redact_fields": [
        "applicant_name", "first_name", "last_name", "phone", "location", "profile_url", "member_urn",
        "cover_letter", "headline", "skills", "work_history", "education", "answers", "resume_url",
        "cover_letter_url", "raw_payload"], "partial": 1},
]

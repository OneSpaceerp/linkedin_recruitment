"""LinkedIn endpoints, API versions and enumerations (Talent Solutions LTS 2026-04, Marketing 2026-11)."""

AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
API_BASE = "https://api.linkedin.com"

USERINFO_PATH = "/v2/userinfo"  # OpenID Connect, unversioned
JOB_POSTINGS_PATH = "/rest/simpleJobPostings"
JOB_TASKS_PATH = "/rest/simpleJobPostingTasks"
POSTS_PATH = "/rest/posts"
ORG_ACLS_PATH = "/rest/organizationAcls"
ORGANIZATIONS_PATH = "/rest/organizations"

# LinkedIn-Version header (YYYYMM). Talent (job postings, Apply Connect) and Marketing (posts,
# organizations) are versioned separately; both are editable in LinkedIn Settings.
DEFAULT_TALENT_VERSION = "202604"
DEFAULT_MARKETING_VERSION = "202611"

JOB_URL = "https://www.linkedin.com/jobs/view/{id}/"
POST_URL = "https://www.linkedin.com/feed/update/{urn}/"

# Scopes. Member sign-in (OpenID Connect) is self-serve; organization scopes need the
# Community Management API product on the LinkedIn developer app.
OIDC_SCOPES = ["openid", "profile", "email"]
MEMBER_POST_SCOPES = ["w_member_social"]
ORGANIZATION_SCOPES = ["w_organization_social", "r_organization_social", "rw_organization_admin"]

EMPLOYMENT_STATUSES = ["FULL_TIME", "PART_TIME", "CONTRACT", "INTERNSHIP", "TEMPORARY", "VOLUNTEER", "OTHER"]
EXPERIENCE_LEVELS = [
    "ENTRY_LEVEL", "ASSOCIATE", "MID_SENIOR_LEVEL", "DIRECTOR", "EXECUTIVE", "INTERNSHIP", "NOT_APPLICABLE",
]
LISTING_TYPES = ["BASIC", "PREMIUM"]
OPERATIONS = ["CREATE", "UPDATE", "RENEW", "CLOSE"]
TASK_STATUSES = ["IN_PROGRESS", "SUCCEEDED", "FAILED", "PROCESSED"]

# Desk label -> API value. On-site is LinkedIn's default and is sent by leaving the field out.
WORKPLACE_TYPES = {"On-site": None, "Hybrid": "hybrid", "Remote": "remote"}

DESCRIPTION_MIN = 100
DESCRIPTION_MAX = 25000
POST_COMMENTARY_MAX = 3000
MAX_BATCH = 100

# Frappe HR "Employment Type" names -> LinkedIn employmentStatus. Matching is on a normalised
# key (lowercase, letters only) so "Full-time", "Full Time" and "FULL_TIME" all match.
EMPLOYMENT_TYPE_MAP = {
    "fulltime": "FULL_TIME",
    "permanent": "FULL_TIME",
    "probation": "FULL_TIME",
    "parttime": "PART_TIME",
    "contract": "CONTRACT",
    "contractor": "CONTRACT",
    "commission": "CONTRACT",
    "piecework": "CONTRACT",
    "freelance": "CONTRACT",
    "intern": "INTERNSHIP",
    "internship": "INTERNSHIP",
    "apprentice": "INTERNSHIP",
    "trainee": "INTERNSHIP",
    "temporary": "TEMPORARY",
    "seasonal": "TEMPORARY",
    "volunteer": "VOLUNTEER",
}

# Webhook event type LinkedIn sends for Apply Connect applications.
EXPORT_JOB_APPLICATION = "EXPORT_JOB_APPLICATION"

# Error codes an Apply Connect webhook may return with a non-200 response.
DELIVERY_ERRORS = [
    "MISSING_REQUIRED_RESPONSE", "INPUT_VALIDATION_FAILED", "DUPLICATE_APPLICATION_RECEIVED",
    "JOB_POSTING_CLOSED", "TOO_MANY_REQUESTS", "SIGNATURE_MISMATCH", "TRANSIENT_ERROR", "OTHER",
]

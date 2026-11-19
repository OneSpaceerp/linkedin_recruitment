"""Pure-Python tests of the LinkedIn protocol layer. Run without a bench:

    python -m unittest discover -s linkedin_recruitment/tests -t .

DocType behaviour is tested on a bench with `bench --site test_site run-tests --app linkedin_recruitment`.
"""

import hashlib
import hmac
import json
import unittest
from datetime import UTC, datetime, timedelta

from linkedin_recruitment.linkedin import applications as A
from linkedin_recruitment.linkedin import csv_import
from linkedin_recruitment.linkedin import payloads as P
from linkedin_recruitment.linkedin import signatures as S
from linkedin_recruitment.linkedin.client import LinkedInAPIError, LinkedInClient

LONG = "<p>We are looking for a passionate engineer to design, build and run the services that power our hiring products.</p>"

JOB = {
    "external_id": "acme-HR-OPN-2026-0001",
    "title": "Software Engineer",
    "description": LONG,
    "apply_url": "https://hr.example.com/jobs/acme/software-engineer",
    "location": "Cairo, Egypt",
    "employment_status": "FULL_TIME",
    "workplace_type": "Hybrid",
    "experience_level": "MID_SENIOR_LEVEL",
    "listing_type": "BASIC",
    "job_functions": ["eng", "it"],
    "industries": ["4", "urn:li:industry:96"],
}
COMPANY = {"company_id": "12345678"}

# Sample payload from LinkedIn's "Receive job applications" page (Apply Connect)
APPLICATION = {
    "type": "EXPORT_JOB_APPLICATION",
    "externalJobId": "acme-HR-OPN-2026-0001",
    "jobApplicationId": "urn:li:jobApplication:12345678",
    "jobApplicant": "urn:li:person:abc123",
    "appliedAt": 1602137400011,
    "applicantSkills": [{"skillUrn": "urn:li:skill:12345", "skillName": "Java", "jobMatched": True,
                         "assessmentVerified": True}],
    "questionResponses": {
        "resumeQuestionResponses": {"resumeQuestionAnswer": {"mediaUrl": "https://www.linkedin.com/ambry/?x=1",
                                                             "mediaUrn": "urn:li:media:AgAAA"}},
        "contactInformationQuestionResponses": {
            "firstNameAnswer": {"value": "First"}, "lastNameAnswer": {"value": "Last"},
            "emailAnswer": {"value": "Applicant@LinkedIn.com"},
            "cellphoneNumberQuestionAnswer": {"countryCode": "20", "nationalNumber": "1001234567"},
        },
        "voluntarySelfIdentificationQuestionResponses": {"disabilityAnswer": "NO", "genderAnswer": "MALE",
                                                         "raceAnswer": "ASIAN", "veteranStatusAnswer": "NOT_PROTECTED_VETERAN"},
        "educationQuestionResponses": {"educationExperienceQuestionSetResponses": [{"school": {"value": "UC Berkeley"}}]},
        "workQuestionResponses": {"workExperienceQuestionSetResponses": [
            {"company": {"value": "LinkedIn"}, "title": {"value": "Software Engineer"}}]},
        "locationAnswer": {"locationStateAnswer": "San Francisco, California, United States",
                           "locationCityAnswer": "San Francisco", "locationCountryAnswer": "US"},
        "additionalQuestionResponses": {"customQuestionSetResponses": [{"customQuestionResponses": [
            {"questionIdentifier": "question1", "answer": {"multipleChoiceAnswerValue": {"symbolicNames": ["right"]}}}]}]},
    },
}


class TestJobPayload(unittest.TestCase):
    def test_full_element(self):
        el = P.job_posting_element(JOB, COMPANY, "CREATE", now=datetime(2026, 11, 19, tzinfo=UTC))
        self.assertEqual(el["externalJobPostingId"], "acme-HR-OPN-2026-0001")
        self.assertEqual(el["jobPostingOperationType"], "CREATE")
        self.assertEqual(el["company"], "urn:li:company:12345678")
        self.assertEqual(el["workplaceTypes"], ["hybrid"])
        self.assertEqual(el["industries"], ["urn:li:industry:4", "urn:li:industry:96"])
        self.assertEqual(el["jobFunctions"], ["eng", "it"])
        self.assertEqual(el["listedAt"], 1795046400000)  # 2026-11-19T00:00Z
        self.assertNotIn("onsiteApplyConfiguration", el)

    def test_onsite_is_default_and_omitted(self):
        el = P.job_posting_element({**JOB, "workplace_type": "On-site"}, COMPANY)
        self.assertNotIn("workplaceTypes", el)

    def test_integration_context_wins(self):
        el = P.job_posting_element(JOB, {"integration_context": "urn:li:organization:1", "company_id": "2"})
        self.assertEqual(el["integrationContext"], "urn:li:organization:1")
        self.assertNotIn("company", el)

    def test_listed_at_never_in_future(self):
        now = datetime(2026, 1, 1, tzinfo=UTC)
        el = P.job_posting_element({**JOB, "listed_at": now + timedelta(days=3)}, COMPANY, now=now)
        self.assertEqual(el["listedAt"], P.epoch_ms(now))

    def test_problems_are_all_reported(self):
        bad = {**JOB, "title": "", "description": "<p>short</p>", "location": "", "apply_url": "jobs/1",
               "listing_type": "PREMIUM", "job_functions": ["a", "b", "c", "d"]}
        with self.assertRaises(P.PayloadError) as ctx:
            P.job_posting_element(bad, {})
        text = " ".join(ctx.exception.problems)
        for expected in ("Job Title", "100 characters", "location", "apply URL", "contract URN", "three", "Organization ID"):
            self.assertIn(expected, text)

    def test_apply_connect_needs_https(self):
        job = {**JOB, "apply_connect": {"webhook_url": "http://insecure.example.com/hook"}}
        self.assertTrue(any("HTTPS" in p for p in P.validate_job(job, COMPANY)))
        job["apply_connect"]["webhook_url"] = "https://hr.example.com/api/method/x"
        el = P.job_posting_element(job, COMPANY)
        self.assertEqual(el["onsiteApplyConfiguration"]["jobApplicationWebhookUrl"], "https://hr.example.com/api/method/x")
        self.assertEqual(el["onsiteApplyConfiguration"]["questions"]["resumeQuestions"]["resumeQuestionRequirement"], "REQUIRED")

    def test_employment_status_mapping(self):
        cases = {"Full-time": "FULL_TIME", "Part-time": "PART_TIME", "Intern": "INTERNSHIP", "Apprentice": "INTERNSHIP",
                 "Contract": "CONTRACT", "Probation": "FULL_TIME", "Piecework": "CONTRACT", "Something": "OTHER",
                 None: "FULL_TIME", "FULL_TIME": "FULL_TIME"}
        for given, expected in cases.items():
            self.assertEqual(P.employment_status(given), expected, given)

    def test_clean_description(self):
        html = ('<div style="color:red" class="x"><h2>About</h2><p onclick="x()">Hello <b>team</b> &amp; '
                '<span>friends</span></p><script>alert(1)</script><style>p{}</style><ul><li a="1">One</li></ul></div>')
        clean = P.clean_description(html)
        self.assertEqual(clean, "<p><b>About</b></p><p>Hello <b>team</b> &amp; friends</p><ul><li>One</li></ul>")
        self.assertNotIn("style", clean)
        self.assertNotIn("alert", clean)

    def test_batch_response(self):
        body = {"elements": [
            {"id": "urn:li:simpleJobPostingTask:1", "entity": {"externalJobPostingId": "a"}, "status": 202},
            {"error": {"code": "ERROR_INVALID_LISTED_AT_FIELD", "message": "future", "status": 400,
                       "errorDetails": {"externalJobPostingId": "b"}}, "status": 400},
        ]}
        ok, bad = P.parse_batch_response(body)
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["task_urn"], "urn:li:simpleJobPostingTask:1")
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["external_id"], "b")
        self.assertIn("ERROR_INVALID_LISTED_AT_FIELD", bad["error"])

    def test_task_summary(self):
        body = {"results": {
            "urn:li:simpleJobPostingTask:x-1": {"id": "urn:li:simpleJobPostingTask:x-1", "status": "SUCCEEDED",
                                                "jobPosting": "urn:li:jobPosting:4215800322", "externalJobPostingId": "a"},
            "urn:li:simpleJobPostingTask:x-2": {"id": "urn:li:simpleJobPostingTask:x-2", "status": "FAILED",
                                                "errorMessage": "missing location", "externalJobPostingId": "a"},
        }, "statuses": {}, "errors": {}}
        state, urn, error = P.summarise_tasks(P.parse_task_results(body))
        self.assertEqual(state, "succeeded")
        self.assertEqual(urn, "urn:li:jobPosting:4215800322")
        self.assertEqual(error, "missing location")
        self.assertEqual(P.job_url(urn), "https://www.linkedin.com/jobs/view/4215800322/")
        self.assertEqual(P.summarise_tasks([{"status": "IN_PROGRESS", "error": "", "job_posting_urn": ""}])[0], "pending")
        self.assertEqual(P.summarise_tasks([{"status": "FAILED", "error": "", "job_posting_urn": ""}])[0], "failed")


class TestPostPayload(unittest.TestCase):
    def test_article_post(self):
        body = P.post_payload("urn:li:organization:5515715", "We're hiring (2 roles) #now", link="https://x.io/j",
                              title="Engineer", description="<p>Great <b>team</b></p>", tags="hiring, Cairo jobs, #Hiring")
        self.assertEqual(body["commentary"], "We're hiring \\(2 roles\\) \\#now\n\n#hiring #CairoJobs")
        self.assertEqual(body["content"]["article"], {"source": "https://x.io/j", "title": "Engineer",
                                                      "description": "Great team"})
        self.assertEqual(body["distribution"]["feedDistribution"], "MAIN_FEED")
        self.assertEqual(body["lifecycleState"], "PUBLISHED")

    def test_post_validation(self):
        with self.assertRaises(P.PayloadError):
            P.post_payload("urn:li:company:1", "")
        with self.assertRaises(P.PayloadError):
            P.post_payload("urn:li:person:abc", "x" * 3001)


class TestSignatures(unittest.TestCase):
    secret = "s3cr3t"

    def test_challenge(self):
        expected = hmac.new(b"s3cr3t", b"890e4665-4dfe-4ab1-b689-ed553bceeed0", hashlib.sha256).hexdigest()
        body = S.challenge_body("890e4665-4dfe-4ab1-b689-ed553bceeed0", self.secret)
        self.assertEqual(body["challengeResponse"], expected)
        self.assertEqual(body["challengeCode"], "890e4665-4dfe-4ab1-b689-ed553bceeed0")

    def test_signature_with_and_without_prefix(self):
        raw = json.dumps(APPLICATION).encode()
        digest = hmac.new(b"s3cr3t", b"hmacsha256=" + raw, hashlib.sha256).hexdigest()
        self.assertTrue(S.verify_signature(raw, digest, self.secret))
        self.assertTrue(S.verify_signature(raw, "hmacsha256=" + digest, self.secret))
        self.assertTrue(S.verify_signature(raw, digest.upper(), self.secret))
        self.assertFalse(S.verify_signature(raw + b" ", digest, self.secret))
        self.assertFalse(S.verify_signature(raw, digest, "other"))
        self.assertFalse(S.verify_signature(raw, "", self.secret))
        self.assertTrue(S.verify_any(raw, digest, ["", "old", self.secret]))


class TestApplications(unittest.TestCase):
    def test_parse_sample(self):
        a = A.parse(APPLICATION)
        self.assertEqual(a["applicant_name"], "First Last")
        self.assertEqual(a["email"], "applicant@linkedin.com")
        self.assertEqual(a["phone"], "+20 1001234567")
        self.assertEqual(a["location"], "San Francisco, California, United States, US")
        self.assertEqual(a["resume_url"], "https://www.linkedin.com/ambry/?x=1")
        self.assertEqual(a["work_history"], ["Software Engineer at LinkedIn"])
        self.assertEqual(a["education"], ["UC Berkeley"])
        self.assertEqual(a["skills"], ["Java"])
        self.assertEqual(a["answers"], [{"section": "Additional", "question": "question1", "answer": "right"}])
        self.assertEqual(a["applied_at"], datetime(2020, 10, 8, 6, 10, 0, 11000))

    def test_redact_removes_self_identification(self):
        clean = A.redact(APPLICATION)
        text = json.dumps(clean)
        for value in ("MALE", "ASIAN", "NOT_PROTECTED_VETERAN"):
            self.assertNotIn(value, text)
        self.assertIn("applicant@linkedin.com".lower(), text.lower())
        self.assertIn("NOT_PROTECTED_VETERAN", json.dumps(APPLICATION))  # original untouched

    def test_missing_contact(self):
        broken = json.loads(json.dumps(APPLICATION))
        del broken["questionResponses"]["contactInformationQuestionResponses"]["emailAnswer"]
        with self.assertRaises(ValueError):
            A.parse(broken)
        with self.assertRaises(ValueError):
            A.parse({**APPLICATION, "type": "SOMETHING_ELSE"})

    def test_delivery_error(self):
        self.assertEqual(A.delivery_error("JOB_POSTING_CLOSED"), {"errors": [{"errorCode": "JOB_POSTING_CLOSED"}]})
        self.assertEqual(A.delivery_error("NOPE")["errors"][0]["errorCode"], "OTHER")


class TestCsvImport(unittest.TestCase):
    def test_aliases_and_dedupe(self):
        text = ("\ufeffFirst Name;Last Name;Email Address;Phone Number;Profile URL;Current Title\n"
                "Mona;Saleh;MONA@example.com;+20 100 000;linkedin.com/in/mona;Engineer\n"
                ";;not-an-email;;;\n"
                "Mona;S;mona@example.com;;;\n")
        rows, problems = csv_import.parse_rows(text.encode("utf-8"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["applicant_name"], "Mona Saleh")
        self.assertEqual(rows[0]["email"], "mona@example.com")
        self.assertEqual(rows[0]["profile_url"], "https://linkedin.com/in/mona")
        self.assertEqual(rows[0]["headline"], "Engineer")
        self.assertEqual(len(problems), 2)

    def test_no_email_column(self):
        rows, problems = csv_import.parse_rows("Name,Phone\nA,1\n")
        self.assertEqual(rows, [])
        self.assertIn("No email column", problems[0])


class FakeResponse:
    def __init__(self, status, body=None, headers=None, content=b""):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.text = json.dumps(body) if body is not None else ""
        self._content = content

    def json(self):
        return self._body

    def iter_content(self, size):
        yield self._content

    def close(self):
        pass


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class TestClient(unittest.TestCase):
    def make(self, responses):
        logs = []
        session = FakeSession(responses)
        client = LinkedInClient("id", "secret", session=session, logger=logs.append, sleep=lambda s: None)
        return client, session, logs

    def test_retries_then_succeeds(self):
        client, session, logs = self.make([
            FakeResponse(429, {"message": "slow down"}, {"Retry-After": "1"}),
            ConnectionError("reset"),
            FakeResponse(200, {"elements": [{"id": "urn:li:simpleJobPostingTask:1", "status": 202}]}),
        ])
        body = client.submit_job_postings("tok", [{"x": 1}])
        self.assertEqual(body["elements"][0]["status"], 202)
        self.assertEqual(len(session.calls), 3)
        _method, url, kw = session.calls[-1]
        self.assertEqual(url, "https://api.linkedin.com/rest/simpleJobPostings")
        self.assertEqual(kw["headers"]["X-Restli-Method"], "batch_create")
        self.assertEqual(kw["headers"]["LinkedIn-Version"], "202604")
        self.assertNotIn("X-Restli-Protocol-Version", kw["headers"])
        self.assertEqual([entry["attempt"] for entry in logs], [1, 2, 3])

    def test_error_is_raised_with_details(self):
        client, _, _ = self.make([FakeResponse(403, {"message": "Not enough permissions", "status": 403},
                                               {"x-li-uuid": "req-1"})])
        with self.assertRaises(LinkedInAPIError) as ctx:
            client.create_post("tok", {})
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(ctx.exception.request_id, "req-1")
        self.assertIn("Not enough permissions", str(ctx.exception))

    def test_token_secrets_not_logged(self):
        client, session, logs = self.make([FakeResponse(200, {"access_token": "AQV", "expires_in": "1800"})])
        body = client.client_credentials_token()
        self.assertEqual(body["expires_in"], 1800)
        self.assertEqual(session.calls[0][2]["data"]["grant_type"], "client_credentials")
        self.assertEqual(logs[0]["request_body"]["client_secret"], "***")
        self.assertEqual(logs[0]["response_body"]["access_token"], "***")

    def test_post_urn_from_header_and_task_query(self):
        client, session, _ = self.make([
            FakeResponse(201, None, {"x-restli-id": "urn:li:share:684"}),
            FakeResponse(200, {"results": {}}),
        ])
        self.assertEqual(client.create_post("tok", {"a": 1}), "urn:li:share:684")
        self.assertEqual(session.calls[0][2]["headers"]["X-Restli-Protocol-Version"], "2.0.0")
        client.job_posting_tasks("tok", ["urn:li:simpleJobPostingTask:a-1", "urn:li:simpleJobPostingTask:b"])
        self.assertTrue(session.calls[1][1].endswith(
            "?ids=urn%3Ali%3AsimpleJobPostingTask%3Aa-1&ids=urn%3Ali%3AsimpleJobPostingTask%3Ab"))

    def test_authorize_url(self):
        client, _, _ = self.make([])
        url = client.authorize_url("https://hr.example.com/api/method/cb", ["openid", "profile"], "st")
        self.assertIn("response_type=code", url)
        self.assertIn("scope=openid%20profile", url)
        self.assertIn("redirect_uri=https%3A%2F%2Fhr.example.com%2Fapi%2Fmethod%2Fcb", url)

    def test_download_limit(self):
        client, _, _ = self.make([FakeResponse(200, None, {"Content-Type": "application/pdf"}, content=b"x" * 20)])
        with self.assertRaises(LinkedInAPIError):
            client.download("https://www.linkedin.com/ambry/?x=1", "tok", max_bytes=10)


if __name__ == "__main__":
    unittest.main()

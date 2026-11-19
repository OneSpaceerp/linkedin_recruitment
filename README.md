<div align="center">
<a href="https://github.com/OneSpaceerp/linkedin_recruitment">
<img src=".github/logo.png" height="96px" width="96px" alt="LinkedIn Recruitment logo">
</a>
<h2>LinkedIn Recruitment</h2>
<p align="center">
<p>Connects Frappe HR recruitment to LinkedIn: publish Job Openings as LinkedIn jobs and company posts, receive Easy Apply applicants as Job Applicants, and let candidates apply with their LinkedIn profile</p>
</p>

[![CI](https://github.com/OneSpaceerp/linkedin_recruitment/actions/workflows/ci.yml/badge.svg)](https://github.com/OneSpaceerp/linkedin_recruitment/actions/workflows/ci.yml)
![Frappe v16](https://img.shields.io/badge/Frappe%20%2F%20ERPNext-v16-0089FF)
![Python 3.14](https://img.shields.io/badge/python-3.14-3776AB)
![License GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-green)

<a href="#installation">Install</a> - <a href="#key-features">Features</a> - <a href="#development">Development</a>
</div>

## LinkedIn Recruitment

LinkedIn Recruitment connects Frappe HR recruiting (Job Opening, Job Applicant) to LinkedIn. Recruiters publish an opening as a LinkedIn job or announce it on the company page from the Job Opening form. Applications from LinkedIn arrive as Job Applicants with the CV attached, and candidates can apply from a page where they sign in with LinkedIn.

It is built for HR teams that already run hiring in ERPNext and Frappe HR. Job Opening, Job Applicant, interviews and offers stay standard Frappe HR documents. The app adds a **LinkedIn** tab to Job Opening and a **LinkedIn** section to Job Applicant, plus its own records for jobs, posts, applicants and the sync log.

### Motivation

Without an integration, every opening is typed twice: once in ERPNext and again on LinkedIn. Candidates then reach HR through LinkedIn messages and email attachments that someone copies into Job Applicants by hand. Jobs stay open on LinkedIn after the position is filled, and there is no record of what was sent or why LinkedIn refused it.

### Key Features

- **Publish Job Openings as LinkedIn jobs.** Tick *Publish on LinkedIn* on a Job Opening. The app sends title, description, location, workplace type, employment type, experience level, job functions and industries through LinkedIn's Job Posting API, then tracks the job until it is live. Saving the opening sends an update, and closing it closes the LinkedIn job.
- **Announce openings on the company page.** One click drafts a LinkedIn post from a template you control, with a link card to the job, and posts it as the organization or as a member. Posts can be deleted from LinkedIn from the same form.
- **LinkedIn Easy Apply into Frappe HR (Apply Connect).** LinkedIn sends each application to the site's webhook. It becomes a LinkedIn Applicant and a Job Applicant with source *LinkedIn*, the CV is downloaded as a private file, and work history, education, skills and screening answers are kept. Signatures are verified, duplicate deliveries are refused the way LinkedIn expects, and closed jobs are reported back as closed.
- **Apply with LinkedIn page.** `/linkedin-apply/<job opening>` lets candidates sign in with LinkedIn (name and verified email) and upload a CV. The page works on phones, follows the system dark mode, and only asks for what LinkedIn does not provide.
- **Import LinkedIn exports.** Upload a CSV exported from LinkedIn Recruiter or a job's applicant list. Common header names are recognised, and rows already in the system are reported rather than duplicated.
- **Every call is logged.** Each request to LinkedIn is stored in the LinkedIn Sync Log with its status, duration and LinkedIn request id. Tokens and secrets are never stored there. Failed jobs and posts show LinkedIn's reason on the record itself.
- **Privacy by default.** Voluntary self-identification answers (gender, race, disability, veteran status) and verification data are removed before anything is stored. Applicant records are covered by Frappe's personal data deletion, and logs and webhook events are purged after the retention you set.
- **Reports and workspace.** The *LinkedIn Hiring Funnel* report shows, per opening, the LinkedIn job state, applicants by channel and how far they got in Frappe HR. The workspace has number cards for live jobs, new applicants, applicants needing attention and sync errors, plus a weekly applicants chart.
- **Arabic and English.** Desk labels and the apply page are translated (`locale/ar.po`).

### What needs LinkedIn approval

LinkedIn decides which APIs a developer app may use. The app works with whatever your LinkedIn app has; each feature has its own switch in **LinkedIn Settings**.

| Feature | LinkedIn product on your developer app | Self-serve? |
| --- | --- | --- |
| Apply with LinkedIn page, connecting accounts | Sign In with LinkedIn using OpenID Connect | Yes |
| Posts as a member | Share on LinkedIn | Yes |
| Posts as the company page | Community Management API | Application and review |
| Publish jobs (Job Posting API) | Job Posting API partner access | LinkedIn partner program |
| Easy Apply into Frappe HR | Apply Connect | LinkedIn partner program |

Without partner access you can still announce jobs on the company page, link them to the Apply with LinkedIn page or your careers page, and import applicant exports.

### Under the Hood

- [**Frappe Framework**](https://github.com/frappe/frappe), [**ERPNext**](https://github.com/frappe/erpnext) and [**Frappe HR**](https://github.com/frappe/hrms) v16.
- LinkedIn REST APIs: Job Posting API (`/rest/simpleJobPostings`, version 202604), Apply Connect webhooks, Posts API (`/rest/posts`, version 202611) and OpenID Connect `userinfo`. API versions are settings, so a LinkedIn version change does not need a release.
- The LinkedIn layer (`linkedin_recruitment/linkedin/`) is plain Python with no Frappe imports: payload builders, HTML clean-up for job descriptions, HMAC-SHA256 webhook checks, the applicant parser and an HTTP client that retries 429 and 5xx with back-off. It is unit-tested without a bench.
- Jobs, posts, resume downloads and imports run in background jobs. The webhook answers LinkedIn immediately and does the heavy work after commit.
- OAuth `state` values are random, single use and expire after ten minutes. Candidate tokens are never stored: only the profile is cached for 30 minutes. Member tokens live in Password fields.

## Installation

Requirements: Frappe and ERPNext, Frappe HR **v16**, Python 3.14. LinkedIn sign-in and webhooks need the site on **HTTPS**.

```bash
cd frappe-bench
bench get-app https://github.com/OneSpaceerp/linkedin_recruitment.git
bench --site your.site install-app linkedin_recruitment
bench build --app linkedin_recruitment
bench restart
```

Installing creates the **LinkedIn Manager** role, the LinkedIn tab on Job Opening and the LinkedIn section on Job Applicant (fields prefixed `li_`), the *LinkedIn* Job Applicant Source, and LinkedIn's 35 job function codes. Every step is safe to repeat and runs again on `bench migrate`. Uninstalling removes the custom fields.

### First steps

1. On [linkedin.com/developers](https://www.linkedin.com/developers/apps), create or open your app and add the products you are entitled to (see the table above).
2. In Desk, open **LinkedIn Recruitment Setup → LinkedIn Settings**. Copy the *Authorized Redirect URL* into the app's **Auth** tab, then enter the **Client ID** and **Client Secret**, your **LinkedIn Organization ID**, and tick **Enable LinkedIn Integration**.
3. Turn on the features you will use (**Job Postings**, **Company Posts**, **Applicants** tabs), then click **Test Connection**.
4. For company posts: **LinkedIn Recruitment Setup → LinkedIn Accounts → New**, save, click **Connect**, and sign in as a page admin. Choose that account under **Company Posts → Post With Account**.
5. Give recruiters the **HR Manager** or **HR User** role, and give the people who manage the integration **LinkedIn Manager**.
6. Open a **Job Opening**, fill the **LinkedIn** tab, and use **LinkedIn → Publish on LinkedIn** or **Announce on LinkedIn**. Progress shows on the form and in **LinkedIn Recruitment → LinkedIn Jobs**.
7. Applicants appear in **LinkedIn Talent → LinkedIn Applicants** and as Job Applicants. Delivery problems are in **LinkedIn Sync → Webhook Events**.

## How jobs move

| LinkedIn Job Posting status | Meaning |
| --- | --- |
| Draft | Created, not sent yet |
| In Progress | Sent; LinkedIn is processing it (checked every 10 minutes, or **Check Status Now**) |
| Listed | Live on LinkedIn, with a link to the job |
| Closing / Closed | Close sent / confirmed |
| Failed | LinkedIn refused it; the reason is on the record and in the Sync Log |

Saving an open Job Opening with *Publish on LinkedIn* sends an update only when a field LinkedIn shows has changed. A Job Opening closed by Frappe HR's own expiry job is closed on LinkedIn by the daily reconciliation. Reopening a closed job creates a new LinkedIn job with a new external id, because LinkedIn does not reopen closed jobs.

## Scheduled jobs

| When | What |
| --- | --- |
| Every 10 minutes | Read LinkedIn's task status for jobs being published or closed |
| Hourly | Process Apply Connect events that failed or were not picked up (up to 5 attempts) |
| Daily | Close LinkedIn jobs of closed openings; renew member tokens or notify the person who connected them; delete old logs and events |

## Development

```bash
# logic tests (no bench needed)
python -m unittest discover -s linkedin_recruitment/tests -t .
python -m compileall -q linkedin_recruitment
ruff check linkedin_recruitment
```

Integration behaviour (DocTypes, hooks, webhooks) needs a bench: `bench --site test_site run-tests --app linkedin_recruitment`. LinkedIn webhooks need a public HTTPS URL; LinkedIn does not accept ngrok.

### Project layout

```text
linkedin_recruitment/
└── linkedin_recruitment/
    ├── linkedin/                 LinkedIn protocol layer, no frappe: payloads, signatures, applications, CSV, client
    ├── services/                 Frappe side: settings and tokens, jobs, posts, applicants, OAuth, importer
    ├── api/                      whitelisted endpoints: jobs, admin, OAuth callback, webhook, apply page
    ├── linkedin_recruitment/     LinkedIn Recruitment: settings, accounts, job postings, posts, job functions, workspace
    ├── linkedin_talent/          LinkedIn Talent: applicants, imports, Hiring Funnel report, applicants chart
    ├── linkedin_sync/            LinkedIn Sync: sync log, webhook events
    ├── www/                      /linkedin-apply page (Apply with LinkedIn)
    ├── data/job_functions.json   LinkedIn job function codes seeded on install
    ├── dock/  desktop_icon/      v16 Dock and app grid; Sidebars live in each module
    ├── public/icons/             module icon sprite (-duotone and -soft symbols)
    ├── public/js/                LinkedIn actions on Job Opening and Job Applicant
    ├── tasks.py                  scheduled jobs
    └── locale/ar.po              Arabic for Desk and the apply page
```

## Trademarks

LinkedIn and the LinkedIn logo are trademarks of LinkedIn Corporation. This app is not made or endorsed by LinkedIn. Follow LinkedIn's API Terms of Use and brand guidelines when you publish it.

## License

GNU General Public License v3.0. See [license.txt](license.txt).

Published by **nsdLabs**, Nest Software Development · [info@nsd-eg.com](mailto:info@nsd-eg.com)

<br/><br/>
<div align="center" style="padding-top: 0.75rem;">
	<a href="mailto:info@nsd-eg.com" target="_blank">
		<picture>
			<source media="(prefers-color-scheme: dark)" srcset=".github/nsdlabs-dark.png">
			<img src=".github/nsdlabs.png" alt="nsdLabs - Nest Software Development" height="44"/>
		</picture>
	</a>
</div>

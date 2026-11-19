// Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
// For license information, please see license.txt

// Quick links from a Job Applicant that came from LinkedIn.
frappe.ui.form.on("Job Applicant", {
	refresh(frm) {
		if (frm.doc.li_profile_url) {
			frm.add_custom_button(__("LinkedIn Profile"), () => window.open(frm.doc.li_profile_url, "_blank", "noopener"), __("LinkedIn"));
		}
		if (frm.doc.li_applicant) {
			frm.add_custom_button(__("LinkedIn Application"), () => frappe.set_route("Form", "LinkedIn Applicant", frm.doc.li_applicant), __("LinkedIn"));
			frm.dashboard.add_indicator(__("Applied through LinkedIn"), "blue");
		}
	},
});

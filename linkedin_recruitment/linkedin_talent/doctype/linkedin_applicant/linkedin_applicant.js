// Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
// For license information, please see license.txt

frappe.ui.form.on("LinkedIn Applicant", {
	refresh(frm) {
		const colors = { Imported: "green", Duplicate: "blue", Received: "orange", Failed: "red", Ignored: "gray" };
		frm.page.set_indicator(__(frm.doc.status), colors[frm.doc.status] || "gray");
		if (frm.is_new()) return;

		if (frm.doc.job_applicant) {
			frm.add_custom_button(__("Job Applicant"), () => frappe.set_route("Form", "Job Applicant", frm.doc.job_applicant));
		} else if (frm.doc.job_opening) {
			frm.add_custom_button(__("Create Job Applicant"), () =>
				frappe
					.call({ method: "linkedin_recruitment.api.admin.make_job_applicant", args: { applicant: frm.doc.name }, freeze: true })
					.then(({ message }) => {
						frm.reload_doc();
						frappe.show_alert({ message: __("Job Applicant {0}", [message]), indicator: "green" });
					})
			).addClass("btn-primary");
		}
		if (frm.doc.profile_url) {
			frm.add_custom_button(__("LinkedIn Profile"), () => window.open(frm.doc.profile_url, "_blank", "noopener"));
		}
		if (!frm.doc.resume && frm.doc.resume_url) {
			frm.add_custom_button(__("Download Resume"), () =>
				frappe.call({ method: "linkedin_recruitment.api.admin.download_resume", args: { applicant: frm.doc.name }, freeze: true }).then(() => frm.reload_doc())
			, __("Actions"));
		}
	},
});

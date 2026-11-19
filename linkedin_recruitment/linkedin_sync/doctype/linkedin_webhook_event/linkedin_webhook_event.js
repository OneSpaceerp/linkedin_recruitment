// Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
// For license information, please see license.txt

frappe.ui.form.on("LinkedIn Webhook Event", {
	refresh(frm) {
		const colors = { Processed: "green", Queued: "blue", Failed: "red", Ignored: "gray", Rejected: "red" };
		frm.page.set_indicator(__(frm.doc.status), colors[frm.doc.status] || "gray");
		if (["Failed", "Queued"].includes(frm.doc.status) && frm.doc.dedupe_key) {
			frm.add_custom_button(__("Process Again"), () =>
				frappe
					.call({ method: "linkedin_recruitment.api.admin.reprocess_event", args: { event: frm.doc.name }, freeze: true })
					.then(() => frm.reload_doc())
			);
		}
		if (frm.doc.linkedin_applicant) {
			frm.add_custom_button(__("LinkedIn Applicant"), () => frappe.set_route("Form", "LinkedIn Applicant", frm.doc.linkedin_applicant));
		}
	},
});

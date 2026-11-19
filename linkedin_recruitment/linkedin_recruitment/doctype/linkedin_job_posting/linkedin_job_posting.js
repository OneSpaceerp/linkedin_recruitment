// Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
// For license information, please see license.txt

frappe.ui.form.on("LinkedIn Job Posting", {
	refresh(frm) {
		const colors = { Listed: "green", "In Progress": "orange", Queued: "orange", Closing: "orange", Failed: "red", Closed: "gray", Draft: "gray" };
		frm.page.set_indicator(__(frm.doc.status), colors[frm.doc.status] || "gray");
		if (frm.is_new()) return;

		const call = (method, args, msg) =>
			frappe
				.call({ method: `linkedin_recruitment.api.jobs.${method}`, args, freeze: true, freeze_message: msg })
				.then(({ message: r }) => {
					if (r && r.status === "Failed") {
						frappe.msgprint({ title: __("LinkedIn"), message: frappe.utils.escape_html(r.error || ""), indicator: "red" });
					}
					frm.reload_doc();
				});
		const live = ["Listed", "In Progress", "Queued"].includes(frm.doc.status);

		frm.add_custom_button(__("Preview Payload"), () =>
			frappe.call("linkedin_recruitment.api.jobs.preview_posting", { posting: frm.doc.name }).then(({ message: r }) => {
				const body = r.problems && r.problems.length
					? `<ul>${r.problems.map((p) => `<li>${frappe.utils.escape_html(p)}</li>`).join("")}</ul>`
					: `<pre style="max-height:60vh;overflow:auto">${frappe.utils.escape_html(JSON.stringify(r.element, null, 2))}</pre>`;
				frappe.msgprint({ title: r.problems && r.problems.length ? __("Fix before publishing") : __("Request to LinkedIn"), message: body, wide: true });
			})
		);
		if (["Draft", "Failed", "Closed"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Publish"), () => call("submit_posting", { posting: frm.doc.name, operation: "CREATE" }, __("Publishing...")), __("LinkedIn"));
		}
		if (frm.doc.status === "Listed") {
			frm.add_custom_button(__("Send Update"), () => call("submit_posting", { posting: frm.doc.name, operation: "UPDATE" }, __("Updating...")), __("LinkedIn"));
			frm.add_custom_button(__("Renew"), () => call("submit_posting", { posting: frm.doc.name, operation: "RENEW" }, __("Renewing...")), __("LinkedIn"));
		}
		if (live) {
			frm.add_custom_button(__("Close"), () =>
				frappe.confirm(__("Close this job on LinkedIn?"), () => call("submit_posting", { posting: frm.doc.name, operation: "CLOSE" }, __("Closing...")))
			, __("LinkedIn"));
		}
		if (frm.doc.task_urns) {
			frm.add_custom_button(__("Check Status Now"), () => call("refresh_posting", { posting: frm.doc.name }, __("Asking LinkedIn...")), __("LinkedIn"));
		}
		if (frm.doc.linkedin_job_url) {
			frm.add_custom_button(__("View on LinkedIn"), () => window.open(frm.doc.linkedin_job_url, "_blank", "noopener"));
		}
		frm.add_custom_button(__("Applicants"), () => frappe.set_route("List", "LinkedIn Applicant", { linkedin_job_posting: frm.doc.name }));
		frm.add_custom_button(__("Sync Log"), () => frappe.set_route("List", "LinkedIn Sync Log", { reference_name: frm.doc.name }));
	},
});

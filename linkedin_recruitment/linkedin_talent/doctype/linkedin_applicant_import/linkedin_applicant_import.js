// Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
// For license information, please see license.txt

frappe.ui.form.on("LinkedIn Applicant Import", {
	refresh(frm) {
		const colors = { Completed: "green", "Completed with Errors": "orange", Failed: "red", Queued: "blue", "In Progress": "blue", Draft: "gray" };
		frm.page.set_indicator(__(frm.doc.status), colors[frm.doc.status] || "gray");
		if (frm.is_new()) {
			frm.set_intro(__("Export applicants from LinkedIn as CSV, attach the file, choose the Job Opening and save."));
			return;
		}
		if (!["Queued", "In Progress"].includes(frm.doc.status) && frm.doc.import_file) {
			frm.add_custom_button(frm.doc.status === "Draft" ? __("Start Import") : __("Import Again"), () =>
				frappe
					.call({ method: "linkedin_recruitment.api.admin.start_import", args: { import_name: frm.doc.name } })
					.then(() => {
						frappe.show_alert({ message: __("Import queued"), indicator: "blue" });
						frm.reload_doc();
					})
			).addClass("btn-primary");
		}
		if (["Queued", "In Progress"].includes(frm.doc.status)) {
			setTimeout(() => frm.reload_doc(), 5000);
		}
		if (frm.doc.imported) {
			frm.add_custom_button(__("Imported Applicants"), () =>
				frappe.set_route("List", "LinkedIn Applicant", { job_opening: frm.doc.job_opening, source: "File Import" })
			);
		}
	},
});

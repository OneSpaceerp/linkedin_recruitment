// Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
// For license information, please see license.txt

// LinkedIn actions on the standard Job Opening form.
frappe.ui.form.on("Job Opening", {
	refresh(frm) {
		if (frm.is_new()) return;
		frappe
			.call("linkedin_recruitment.api.jobs.status", { job_opening: frm.doc.name })
			.then(({ message: s }) => s && s.enabled && linkedin_recruitment_opening.render(frm, s));
	},
});

window.linkedin_recruitment_opening = {
	colors: { Listed: "green", "In Progress": "orange", Queued: "orange", Closing: "orange", Failed: "red", Closed: "gray", Draft: "gray" },

	render(frm, s) {
		const group = __("LinkedIn");
		const posting = s.posting;
		if (posting) {
			frm.dashboard.add_indicator(__("LinkedIn: {0}", [__(posting.status)]), this.colors[posting.status] || "gray");
			if (posting.status === "Failed" && posting.error_message) {
				frm.dashboard.set_headline_alert(
					`<b>${__("LinkedIn")}:</b> ${frappe.utils.escape_html(posting.error_message)}`,
					"red"
				);
			}
		}

		if (s.job_api && s.can_publish) {
			const live = posting && ["Listed", "In Progress", "Queued"].includes(posting.status);
			if (frm.doc.status === "Open") {
				frm.add_custom_button(live ? __("Update LinkedIn Job") : __("Publish on LinkedIn"), () =>
					this.act(frm, "publish", live ? __("Sending the update to LinkedIn...") : __("Publishing on LinkedIn..."))
				, group);
			}
			if (live) {
				frm.add_custom_button(__("Close LinkedIn Job"), () =>
					frappe.confirm(__("Close this job on LinkedIn? Candidates will no longer see it."), () =>
						this.act(frm, "close", __("Closing on LinkedIn..."))
					)
				, group);
			}
		}
		if (posting) {
			frm.add_custom_button(__("LinkedIn Job Posting"), () => frappe.set_route("Form", "LinkedIn Job Posting", posting.name), group);
			if (posting.linkedin_job_url) {
				frm.add_custom_button(__("View on LinkedIn"), () => window.open(posting.linkedin_job_url, "_blank", "noopener"), group);
			}
		}
		if (s.posts && s.can_post && frm.doc.status === "Open") {
			frm.add_custom_button(__("Announce on LinkedIn"), () =>
				frappe
					.call({ method: "linkedin_recruitment.api.jobs.draft_post", args: { job_opening: frm.doc.name }, freeze: true })
					.then(({ message }) => frappe.set_route("Form", "LinkedIn Post", message))
			, group);
		}
		(s.post_list || []).forEach((p) => {
			if (p.status === "Published" && p.post_url) {
				frm.dashboard.add_indicator(__("Announced on LinkedIn"), "blue");
			}
		});
	},

	act(frm, action, message) {
		frappe
			.call({
				method: `linkedin_recruitment.api.jobs.${action}`,
				args: { job_opening: frm.doc.name },
				freeze: true,
				freeze_message: message,
			})
			.then(({ message: r }) => {
				if (r.status === "Failed") {
					frappe.msgprint({ title: __("LinkedIn did not accept the job"), message: frappe.utils.escape_html(r.error || ""), indicator: "red" });
				} else {
					frappe.show_alert({ message: __("Sent to LinkedIn. It usually goes live within a few minutes."), indicator: "green" });
				}
				frm.reload_doc();
			});
	},
};

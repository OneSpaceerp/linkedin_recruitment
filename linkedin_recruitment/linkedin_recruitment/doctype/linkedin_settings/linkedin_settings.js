// Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
// For license information, please see license.txt

frappe.ui.form.on("LinkedIn Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Test Connection"), () => {
			frappe
				.call({ method: "linkedin_recruitment.api.admin.test_connection", freeze: true, freeze_message: __("Asking LinkedIn...") })
				.then(({ message: checks }) => {
					const rows = (checks || [])
						.map((c) => `<tr><td>${c.ok ? "&#9989;" : "&#10060;"}</td><td><b>${frappe.utils.escape_html(c.check)}</b></td><td>${frappe.utils.escape_html(c.detail || "")}</td></tr>`)
						.join("");
					frappe.msgprint({ title: __("LinkedIn Connection"), message: `<table class="table table-bordered">${rows}</table>`, wide: true });
				});
		});
		frm.add_custom_button(__("Connect a LinkedIn Account"), () => linkedin_recruitment_connect(null), __("Accounts"));
		frm.add_custom_button(__("LinkedIn Accounts"), () => frappe.set_route("List", "LinkedIn Account"), __("Accounts"));
		frm.add_custom_button(__("Sync Log"), () => frappe.set_route("List", "LinkedIn Sync Log"), __("View"));
		frm.add_custom_button(__("Webhook Events"), () => frappe.set_route("List", "LinkedIn Webhook Event"), __("View"));

		frappe.call("linkedin_recruitment.api.admin.setup_info").then(({ message: info }) => {
			if (!info) return;
			frm.set_df_property("redirect_uri", "description",
				__("Add this URL under Authorized redirect URLs for OAuth 2.0 in the LinkedIn app.") + `<br><code>${frappe.utils.escape_html(info.redirect_uri)}</code>`);
			if (!info.https) {
				frm.dashboard.set_headline_alert(__("This site is served over HTTP. LinkedIn sign-in and webhooks need HTTPS in production."), "orange");
			}
		});
	},
	enable_company_posts(frm) {
		if (frm.doc.enable_company_posts && !frm.doc.post_template) {
			frm.set_value("post_template", "We're hiring! Join {{ doc.company }} as {{ doc.job_title }}{% if location %} in {{ location }}{% endif %}.\n\nApply here: {{ apply_url }}");
		}
	},
});

// Opens LinkedIn sign-in for an account (or a new one) in the same tab; LinkedIn returns to the account form.
window.linkedin_recruitment_connect = function (account) {
	frappe
		.call({ method: "linkedin_recruitment.api.admin.connect_account", args: { account }, freeze: true })
		.then(({ message: url }) => {
			if (url) window.location.href = url;
		});
};

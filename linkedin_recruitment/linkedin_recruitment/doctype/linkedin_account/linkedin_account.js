// Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
// For license information, please see license.txt

frappe.ui.form.on("LinkedIn Account", {
	refresh(frm) {
		const colors = { Connected: "green", Expired: "orange", Revoked: "red", "Not Connected": "gray" };
		frm.page.set_indicator(__(frm.doc.status), colors[frm.doc.status] || "gray");
		if (frm.is_new()) {
			frm.set_intro(__("Save, then click Connect to sign in with the LinkedIn member who manages your company page."));
			return;
		}
		frm.add_custom_button(frm.doc.status === "Connected" ? __("Reconnect") : __("Connect"), () => {
			frappe
				.call({ method: "linkedin_recruitment.api.admin.connect_account", args: { account: frm.doc.name }, freeze: true })
				.then(({ message: url }) => url && (window.location.href = url));
		});
		if (frm.doc.status === "Connected") {
			frm.add_custom_button(__("Reload Company Pages"), () =>
				frappe
					.call({ method: "linkedin_recruitment.api.admin.reload_organizations", args: { account: frm.doc.name }, freeze: true })
					.then(() => frm.reload_doc())
			, __("Actions"));
			frm.add_custom_button(__("Disconnect"), () =>
				frappe.confirm(__("Remove the stored LinkedIn tokens for this account?"), () =>
					frappe
						.call({ method: "linkedin_recruitment.api.admin.disconnect_account", args: { account: frm.doc.name } })
						.then(() => frm.reload_doc())
				)
			, __("Actions"));
		}
	},
});

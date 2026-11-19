// Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
// For license information, please see license.txt

frappe.ui.form.on("LinkedIn Post", {
	refresh(frm) {
		const colors = { Published: "green", Failed: "red", Deleted: "gray", Draft: "orange" };
		frm.page.set_indicator(__(frm.doc.status), colors[frm.doc.status] || "gray");
		frm.toggle_enable(["commentary", "hashtags", "link_url", "link_title", "link_description", "visibility", "account", "post_as", "organization_urn"],
			frm.doc.status !== "Published");
		if (frm.is_new()) return;

		if (["Draft", "Failed"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Publish on LinkedIn"), () => {
				if (frm.is_dirty()) {
					frappe.msgprint(__("Save the post first."));
					return;
				}
				frappe
					.call({ method: "linkedin_recruitment.api.jobs.publish_post", args: { post: frm.doc.name }, freeze: true, freeze_message: __("Posting...") })
					.then(({ message: r }) => {
						if (r.status === "Failed") {
							frappe.msgprint({ title: __("LinkedIn did not accept the post"), message: frappe.utils.escape_html(r.error || ""), indicator: "red" });
						} else {
							frappe.show_alert({ message: __("Posted on LinkedIn"), indicator: "green" });
						}
						frm.reload_doc();
					});
			}).addClass("btn-primary");
		}
		if (frm.doc.status === "Published") {
			if (frm.doc.post_url) {
				frm.add_custom_button(__("View on LinkedIn"), () => window.open(frm.doc.post_url, "_blank", "noopener"));
			}
			frm.add_custom_button(__("Delete from LinkedIn"), () =>
				frappe.confirm(__("Delete this post from LinkedIn? This cannot be undone."), () =>
					frappe.call({ method: "linkedin_recruitment.api.jobs.delete_post", args: { post: frm.doc.name }, freeze: true }).then(() => frm.reload_doc())
				)
			, __("Actions"));
		}
	},
	commentary(frm) {
		const n = (frm.doc.commentary || "").length;
		frm.set_df_property("commentary", "description", __("{0} of 3000 characters", [n]));
	},
});

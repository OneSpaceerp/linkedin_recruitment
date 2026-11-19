// Copyright (c) 2026, nsdLabs - Nest Software Development and contributors
// For license information, please see license.txt

frappe.query_reports["LinkedIn Hiring Funnel"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company" },
		{ fieldname: "job_opening", label: __("Job Opening"), fieldtype: "Link", options: "Job Opening" },
		{ fieldname: "from_date", label: __("Applied From"), fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -3) },
		{ fieldname: "to_date", label: __("Applied To"), fieldtype: "Date", default: frappe.datetime.get_today() },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "linkedin_status" && data) {
			const color = { Listed: "green", Failed: "red", Closed: "gray", "In Progress": "orange" }[data.linkedin_status] || "gray";
			value = `<span class="indicator-pill ${color}">${value}</span>`;
		}
		return value;
	},
};

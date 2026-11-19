from frappe import _


def get_data():
    return [
        {"module_name": "LinkedIn Recruitment", "type": "module", "label": _("LinkedIn Recruitment")},
        {"module_name": "LinkedIn Talent", "type": "module", "label": _("LinkedIn Talent")},
        {"module_name": "LinkedIn Sync", "type": "module", "label": _("LinkedIn Sync")},
    ]

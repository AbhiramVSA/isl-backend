"""Role → permission map for the Equal responder console.

Roles are coarse job titles stored on the account; permissions are what the
code checks. Keep checks on permissions so a role can be reshaped here without
touching endpoints.

Scope is separate from permission: ``ADMIN`` and ``AUDITOR`` see every office,
everyone else sees only the offices they are a member of.
"""

import enum

from app.models import Role


class Permission(str, enum.Enum):
    # Report handling
    REPORTS_VIEW = "reports.view"
    REPORTS_RESPOND = "reports.respond"  # take a report and move it through the workflow
    REPORTS_ASSIGN = "reports.assign"  # assign / reassign to another officer
    REPORTS_PRIORITIZE = "reports.prioritize"
    REPORTS_OVERRIDE = "reports.override"  # force a status (cancel, reopen)
    REPORTS_EXPORT = "reports.export"
    # People and places
    STAFF_VIEW = "staff.view"
    STAFF_MANAGE = "staff.manage"
    OFFICES_VIEW = "offices.view"
    OFFICES_MANAGE = "offices.manage"  # create and deactivate offices
    OFFICES_EDIT = "offices.edit"  # edit details of offices in scope
    REPORTERS_VIEW = "reporters.view"
    REPORTERS_MANAGE = "reporters.manage"
    # Oversight
    AUDIT_VIEW = "audit.view"
    ANALYTICS_VIEW = "analytics.view"


P = Permission

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.USER: frozenset(),
    Role.OFFICER: frozenset({P.REPORTS_VIEW, P.REPORTS_RESPOND, P.OFFICES_VIEW}),
    Role.DISPATCHER: frozenset(
        {
            P.REPORTS_VIEW,
            P.REPORTS_RESPOND,
            P.REPORTS_ASSIGN,
            P.REPORTS_PRIORITIZE,
            P.REPORTS_EXPORT,
            P.STAFF_VIEW,
            P.OFFICES_VIEW,
            P.ANALYTICS_VIEW,
        }
    ),
    Role.OFFICE_ADMIN: frozenset(
        {
            P.REPORTS_VIEW,
            P.REPORTS_RESPOND,
            P.REPORTS_ASSIGN,
            P.REPORTS_PRIORITIZE,
            P.REPORTS_OVERRIDE,
            P.REPORTS_EXPORT,
            P.STAFF_VIEW,
            P.STAFF_MANAGE,
            P.OFFICES_VIEW,
            P.OFFICES_EDIT,
            P.REPORTERS_VIEW,
            P.AUDIT_VIEW,
            P.ANALYTICS_VIEW,
        }
    ),
    Role.AUDITOR: frozenset(
        {
            P.REPORTS_VIEW,
            P.REPORTS_EXPORT,
            P.STAFF_VIEW,
            P.OFFICES_VIEW,
            P.REPORTERS_VIEW,
            P.AUDIT_VIEW,
            P.ANALYTICS_VIEW,
        }
    ),
    Role.ADMIN: frozenset(Permission),
}

ROLE_LABELS: dict[Role, str] = {
    Role.USER: "Reporter",
    Role.OFFICER: "Officer",
    Role.DISPATCHER: "Dispatcher",
    Role.OFFICE_ADMIN: "Office Admin",
    Role.AUDITOR: "Auditor",
    Role.ADMIN: "Super Admin",
}

STAFF_ROLES: frozenset[Role] = frozenset(ROLE_PERMISSIONS) - {Role.USER}
GLOBAL_SCOPE_ROLES: frozenset[Role] = frozenset({Role.ADMIN, Role.AUDITOR})
# Roles an office admin may hand out; only a super admin creates admins and auditors.
OFFICE_ADMIN_GRANTABLE: frozenset[Role] = frozenset({Role.OFFICER, Role.DISPATCHER})


def permissions_for(role: Role) -> frozenset[Permission]:
    return ROLE_PERMISSIONS.get(role, frozenset())

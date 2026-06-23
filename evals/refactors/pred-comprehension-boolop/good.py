def active_admins(users):
    return [u for u in users if _is_active_admin(u)]


def _is_active_admin(u):
    return u.active and not u.suspended and u.role == "admin" and u.verified

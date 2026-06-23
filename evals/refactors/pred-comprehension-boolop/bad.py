def active_admins(users):
    return [u for u in users
            if u.active and not u.suspended and u.role == "admin" and u.verified]

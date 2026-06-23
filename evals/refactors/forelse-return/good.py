def find_admin(users):
    for u in users:
        if u.role == "admin":
            return u
    return None

_saved = []


def db_exists(email):
    return email in {u["email"] for u in _saved}


def db_save(user):
    _saved.append(user)


def import_user(payload):
    if not payload:
        return
    if not payload.get("email"):
        return
    if db_exists(payload["email"]):
        return
    user = {"email": payload["email"]}
    db_save(user)

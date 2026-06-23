_saved = []


def db_exists(email):
    return email in {u["email"] for u in _saved}


def db_save(user):
    _saved.append(user)


def import_user(payload):
    if payload:
        if payload.get("email"):
            if not db_exists(payload["email"]):
                user = {"email": payload["email"]}
                db_save(user)

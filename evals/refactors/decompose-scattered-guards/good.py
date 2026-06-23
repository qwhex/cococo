def handle(req):
    log(req)
    _validate(req)
    return commit(req)


def _validate(req):
    if req.token is None:
        raise Unauthorized()
    if req.user is None:
        raise NotFound()
    if req.banned:
        raise Forbidden()
    if not req.payload:
        raise BadRequest()
    if req.expired:
        raise Expired()

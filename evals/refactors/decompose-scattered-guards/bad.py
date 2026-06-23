def handle(req):
    log(req)
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
    return commit(req)

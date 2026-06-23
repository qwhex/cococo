def summarise(a, b, c, d, e):
    header()
    if a:
        p = b + c
        q = d - e
        r = p * q
        if p > 0:
            for i in range(p):
                if q > i:
                    emit(r)
    if a:
        footer()
    return p, q, r

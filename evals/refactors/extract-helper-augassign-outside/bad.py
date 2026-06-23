def process(items, rows):
    seen = 0
    seen += 1
    for item in items:
        if item.ok:
            handle(item)
    for r in rows:
        if r.active:
            for x in r.xs:
                if x.dirty:
                    emit(x)
    seen += 2
    return seen

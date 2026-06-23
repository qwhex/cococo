def f(x, items):
    setup()
    if not x:
        return
    for item in items:
        if item.ok:
            handle(item)

def f(x, items):
    setup()
    if x:
        for item in items:
            if item.ok:
                handle(item)

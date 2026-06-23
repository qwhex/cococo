def process(items):
    for item in items:
        if item.ready:
            for part in item.parts:
                if part.active:
                    handle(part)

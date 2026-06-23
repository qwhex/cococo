def process(items, flag):
    if flag:
        return None
    else:
        for item in items:
            if item.active:
                handle(item)
        return len(items)

def count(enabled, items):
    if not enabled:
        return 0
    total = 0
    for x in items:
        if x > 0:
            total += x
    return total

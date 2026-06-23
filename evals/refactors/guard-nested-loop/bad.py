def count(enabled, items):
    total = 0
    if enabled:
        for x in items:
            if x > 0:
                total += x
    return total

def aggregate(rows):
    total = 0
    count = 0
    weight = 0
    for r in rows:
        if r.active:
            for v in r.values:
                if v > 0:
                    total += v
                    count += 1
                    weight += v * r.factor
    return total, count, weight

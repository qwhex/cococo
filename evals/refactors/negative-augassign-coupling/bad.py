def count_matches(groups):
    found = 0
    for group in groups:
        if group.active:
            for item in group.items:
                if item.matches:
                    found += 1
                    if item.bonus:
                        found += 10
    return found

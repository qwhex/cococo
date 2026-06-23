THRESHOLD = 10


def first_match(items, pred):
    for item in items:
        if (result := pred(item)):
            if result.score > THRESHOLD:
                return result
    return None

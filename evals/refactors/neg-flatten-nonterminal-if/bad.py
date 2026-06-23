def check(n, strict):
    if n < 0:
        if strict:
            return -1
    else:
        for x in range(10):
            if x > 5:
                process(x)
        return 1

_SYMBOLS = {"add": "+", "sub": "-", "mul": "*", "div": "/"}


def symbol(op):
    return _SYMBOLS.get(op, "?")

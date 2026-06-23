def classify(x):
    if x == 1:
        return "int-one"
    if x == True:
        return "bool-true"
    if x == 1.0:
        return "float-one"
    return "other"

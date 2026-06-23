def report(rows, sink):
    counts = {}
    for r in rows:
        if r.kind in counts:
            counts[r.kind] += 1
    for r in rows:
        if r.active:
            for f in r.fields:
                if f.dirty:
                    sink.write(f)
    return counts

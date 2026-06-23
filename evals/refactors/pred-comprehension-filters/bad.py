def big_sales(records):
    return [
        r for r in records
        if r.amount > 1000
        if r.region in ACTIVE_REGIONS
    ]

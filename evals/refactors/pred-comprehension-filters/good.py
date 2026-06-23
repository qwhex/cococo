def big_sales(records):
    return [r for r in records if _is_big_sale(r)]


def _is_big_sale(r):
    return r.amount > 1000 and r.region in ACTIVE_REGIONS

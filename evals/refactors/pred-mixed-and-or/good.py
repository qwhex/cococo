def should_cache(resp, cfg):
    if _is_cacheable(resp, cfg):
        store(resp)


def _is_cacheable(resp, cfg):
    return (resp.status == 200
            and not resp.no_store
            and (resp.public or cfg.force_cache)
            and resp.body)

def should_cache(resp, cfg):
    if resp.status == 200 and not resp.no_store and (resp.public or cfg.force_cache) and resp.body:
        store(resp)

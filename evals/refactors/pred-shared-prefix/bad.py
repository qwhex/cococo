def process(item, cfg):
    if item.ready and item.valid and not item.locked and cfg.enabled:
        run(item)
    elif item.ready and item.valid and not item.locked and cfg.dry_run:
        preview(item)

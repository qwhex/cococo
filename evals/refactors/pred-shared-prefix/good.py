def process(item, cfg):
    if not _item_processable(item):
        return
    if cfg.enabled:
        run(item)
    elif cfg.dry_run:
        preview(item)


def _item_processable(item):
    return item.ready and item.valid and not item.locked

_HANDLERS = {
    "click":   on_click,
    "keydown": on_keydown,
    "resize":  on_resize,
    "scroll":  on_scroll,
    "focus":   on_focus,
}


def dispatch(event):
    handler = _HANDLERS.get(event.kind, on_unknown)
    return handler(event)

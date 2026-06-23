def dispatch(event):
    if event.kind == "click":
        return on_click(event)
    elif event.kind == "keydown":
        return on_keydown(event)
    elif event.kind == "resize":
        return on_resize(event)
    elif event.kind == "scroll":
        return on_scroll(event)
    elif event.kind == "focus":
        return on_focus(event)
    return on_unknown(event)

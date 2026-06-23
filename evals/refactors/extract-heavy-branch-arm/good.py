def handle_event(event):
    if event.kind == "tick":
        clock.advance()
    elif event.kind == "data":
        _handle_data_event(event)
    else:
        log.warn("unknown", event)


def _handle_data_event(event):
    if event.payload:
        for chunk in event.payload.chunks:
            if chunk.ready:
                for item in chunk.items:
                    if item.valid:
                        store.write(item)

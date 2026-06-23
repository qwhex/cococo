def handle_event(event):
    if event.kind == "tick":
        clock.advance()
    elif event.kind == "data":
        if event.payload:
            for chunk in event.payload.chunks:
                if chunk.ready:
                    for item in chunk.items:
                        if item.valid:
                            store.write(item)
    else:
        log.warn("unknown", event)

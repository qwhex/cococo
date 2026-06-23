_STATE_HANDLERS = {
    State.CONNECTING: on_connecting,
    State.CONNECTED:  on_connected,
    State.DRAINING:   on_draining,
    State.CLOSED:     on_closed,
    State.ERROR:      on_error,
}


def handle_state(conn):
    handler = _STATE_HANDLERS.get(conn.state)
    if handler is None:
        raise ValueError(f"unknown state: {conn.state}")
    return handler(conn)

def handle_state(conn):
    if conn.state == State.CONNECTING:
        return on_connecting(conn)
    elif conn.state == State.CONNECTED:
        return on_connected(conn)
    elif conn.state == State.DRAINING:
        return on_draining(conn)
    elif conn.state == State.CLOSED:
        return on_closed(conn)
    elif conn.state == State.ERROR:
        return on_error(conn)
    raise ValueError(f"unknown state: {conn.state}")

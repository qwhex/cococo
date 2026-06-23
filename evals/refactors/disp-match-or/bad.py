def http_label(code):
    match code:
        case 200 | 201 | 204:
            return "success"
        case 301 | 302:
            return "redirect"
        case 400 | 422:
            return "client_error"
        case 404:
            return "not_found"
        case 500 | 503:
            return "server_error"
        case _:
            return "unknown"

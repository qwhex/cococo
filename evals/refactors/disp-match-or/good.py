_HTTP_LABELS = {
    200: "success", 201: "success", 204: "success",
    301: "redirect", 302: "redirect",
    400: "client_error", 422: "client_error",
    404: "not_found",
    500: "server_error", 503: "server_error",
}


def http_label(code):
    return _HTTP_LABELS.get(code, "unknown")

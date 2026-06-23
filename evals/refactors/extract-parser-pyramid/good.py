MAGIC = b"\x89PNG"
SUPPORTED = {1, 2}
KNOWN_TAGS = set()


def split_chunks(body):
    return []


def emit(field):
    pass


def parse_message(data):
    header = data[:4]
    if header == MAGIC:
        _parse_body(header[0], data[4:])
    return True


def _parse_body(version, body):
    if version not in SUPPORTED:
        return
    if not body:
        return
    for chunk in split_chunks(body):
        if chunk.valid:
            for field in chunk.fields:
                if field.tag in KNOWN_TAGS:
                    emit(field)

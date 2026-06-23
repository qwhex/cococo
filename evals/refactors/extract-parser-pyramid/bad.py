MAGIC = b"\x89PNG"
SUPPORTED = {1, 2}


def split_chunks(body):
    return []


def emit(field):
    pass


def parse_message(data):
    header = data[:4]
    if header == MAGIC:
        version = header[0]
        if version in SUPPORTED:
            body = data[4:]
            if body:
                for chunk in split_chunks(body):
                    if chunk.valid:
                        for field in chunk.fields:
                            if field.tag in KNOWN_TAGS:
                                emit(field)
    return True

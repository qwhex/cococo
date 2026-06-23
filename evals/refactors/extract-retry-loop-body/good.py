def fetch_with_retry(url, max_attempts, session):
    for attempt in range(max_attempts):
        result = _try_fetch(url, attempt, max_attempts, session)
        if result is not None:
            return result
    return None


def _try_fetch(url, attempt, max_attempts, session):
    try:
        resp = session.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 429:
            backoff = 2 ** attempt
            time.sleep(backoff)
        else:
            raise HTTPError(resp.status_code)
    except ConnectionError:
        if attempt == max_attempts - 1:
            raise
    return None

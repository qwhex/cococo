def _s3(): return S3Backend(bucket=os.environ["S3_BUCKET"])
def _gcs(): return GCSBackend(project=os.environ["GCP_PROJECT"])
def _azure(): return AzureBackend(container=os.environ["AZURE_CONTAINER"])
def _local(): return LocalBackend(root=os.environ.get("LOCAL_ROOT", "/tmp/store"))
def _memory(): return MemoryBackend()

_BACKEND_FACTORIES = {
    "s3": _s3,
    "gcs": _gcs,
    "azure": _azure,
    "local": _local,
    "memory": _memory,
}


def get_storage_backend(backend_name):
    factory = _BACKEND_FACTORIES.get(backend_name)
    if factory is None:
        raise ConfigError(f"unknown storage backend: {backend_name!r}")
    return factory()

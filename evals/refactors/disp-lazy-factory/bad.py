def get_storage_backend(backend_name):
    if backend_name == "s3":
        return S3Backend(bucket=os.environ["S3_BUCKET"])
    if backend_name == "gcs":
        return GCSBackend(project=os.environ["GCP_PROJECT"])
    if backend_name == "azure":
        return AzureBackend(container=os.environ["AZURE_CONTAINER"])
    if backend_name == "local":
        return LocalBackend(root=os.environ.get("LOCAL_ROOT", "/tmp/store"))
    if backend_name == "memory":
        return MemoryBackend()
    raise ConfigError(f"unknown storage backend: {backend_name!r}")

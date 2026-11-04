"""Konfigurasi pytest untuk semua layer."""


def pytest_metadata(metadata):
    # Jangan bocorkan path/variabel lokal laptop ke HTML report yang dibagikan.
    for key in ("JAVA_HOME", "Base URL"):
        metadata.pop(key, None)

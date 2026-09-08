"""Download only the pinned official Apache-2.0 CPU model; verify bytes and SHA-256."""

import hashlib
import os
import tempfile
import urllib.request
from pathlib import Path

REVISION = "91cad51170dc346986eccefdc2dd33a9da36ead9"
FILENAME = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
SHA256 = "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e"
SIZE = 1117320736
URL = f"https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/{REVISION}/{FILENAME}"


def checksum(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main():
    root = Path(__file__).resolve().parents[1] / "models"
    root.mkdir(exist_ok=True)
    destination = root / FILENAME
    if destination.exists():
        if destination.stat().st_size == SIZE and checksum(destination) == SHA256:
            print("Pinned model already verified.")
            return
        raise SystemExit("Existing model does not match the pin. Move it aside before retrying.")
    print(
        "Downloading 1.12 GB official Qwen GGUF; no inference API or OCI resources are used.",
        flush=True,
    )
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=root, prefix="download-", delete=False) as target:
            temporary = Path(target.name)
            count, hashed = 0, hashlib.sha256()
            with urllib.request.urlopen(URL, timeout=60) as response:
                while chunk := response.read(1024 * 1024):
                    count += len(chunk)
                    if count > SIZE:
                        raise ValueError("Model exceeds pinned size")
                    hashed.update(chunk)
                    target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        if count != SIZE or hashed.hexdigest() != SHA256:
            raise ValueError("Model checksum/size mismatch")
        temporary.chmod(0o644)
        # A competing download must not replace an existing target.
        os.link(temporary, destination)
        print("Model verified: " + SHA256)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()

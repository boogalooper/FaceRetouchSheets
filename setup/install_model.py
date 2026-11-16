"""Install the SCRFD file from the official InsightFace model pack."""
import hashlib
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_NAME = "scrfd_10g_bnkps.onnx"
MODEL_URL = "https://github.com/deepinsight/insightface/releases/download/model-zoo/antelopev2.zip"
ARCHIVE_SHA256 = "8e182f14fc6e80b3bfa375b33eb6cff7ee05d8ef7633e738d1c89021dcf0c5c5"


def install_model(directory):
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / MODEL_NAME
    if destination.is_file():
        print(f"Existing model: {destination}", flush=True)
        return destination

    print("Downloading antelopev2 from InsightFace (~344 MB)...", flush=True)
    with tempfile.TemporaryDirectory(prefix="scrfd-", dir=directory) as temporary:
        archive = Path(temporary) / "antelopev2.zip"
        request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "FaceRetouchSheets/1.0"})
        digest = hashlib.sha256()
        with urllib.request.urlopen(request, timeout=90) as response, archive.open("wb") as out:
            while chunk := response.read(1024 * 1024):
                out.write(chunk)
                digest.update(chunk)
        if digest.hexdigest() != ARCHIVE_SHA256:
            raise ValueError("The downloaded model archive failed SHA-256 verification.")

        with zipfile.ZipFile(archive) as bundle:
            candidates = [item for item in bundle.infolist()
                          if not item.is_dir() and Path(item.filename).name == MODEL_NAME]
            if len(candidates) != 1:
                raise ValueError("The official archive does not contain exactly one SCRFD model.")
            staged = Path(temporary) / MODEL_NAME
            with bundle.open(candidates[0]) as source, staged.open("wb") as out:
                shutil.copyfileobj(source, out)
        staged.replace(destination)
    return destination


if __name__ == "__main__":
    install_model(ROOT / "models")

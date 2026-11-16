"""Load the SCRFD detection model from InsightFace antelopev2."""
from pathlib import Path

import numpy as np

from retouch_sheets import DETECTOR_THRESHOLD

MODEL_NAME = "scrfd_10g_bnkps.onnx"
CPU = "CPUExecutionProvider"
CUDA = "CUDAExecutionProvider"


def find_default_model():
    root = Path(__file__).resolve().parents[1]
    model = root / "models" / MODEL_NAME
    return model if model.is_file() else None


def load_detector(model: Path, device: str, log):
    import onnxruntime as ort
    from insightface.model_zoo import get_model

    def prepare(provider):
        providers = [CUDA, CPU] if provider == CUDA else [CPU]
        detector = get_model(str(model.resolve()), providers=providers)
        if detector is None or getattr(detector, "taskname", None) != "detection":
            raise ValueError(f"Выберите ONNX детектора, например {MODEL_NAME}.")
        detector.prepare(ctx_id=0 if provider == CUDA else -1,
                         input_size=(640, 640), det_thresh=DETECTOR_THRESHOLD)
        detector.detect(np.zeros((640, 640, 3), dtype=np.uint8), max_num=0)
        if provider not in detector.session.get_providers():
            raise RuntimeError(f"ONNX Runtime не активировал {provider}.")
        return detector

    cuda_available = CUDA in ort.get_available_providers()
    if device == "gpu" and not cuda_available:
        raise RuntimeError("CUDA недоступна. Выберите Авто или CPU либо установите CUDA-вариант ONNX Runtime.")
    if device != "cpu" and cuda_available:
        try:
            if hasattr(ort, "preload_dlls"):
                ort.preload_dlls(directory="")
            detector = prepare(CUDA)
        except ValueError:
            raise
        except Exception as exc:
            if device == "gpu":
                raise RuntimeError(f"Не удалось запустить CUDA: {exc}") from exc
            log(f"CUDA недоступна, используется CPU: {exc}")
        else:
            log("Детектор SCRFD: GPU (CUDA)")
            return detector

    detector = prepare(CPU)
    log("Детектор SCRFD: CPU")
    return detector

"""Run by build_installer.bat before PyInstaller.

Makes sure every file the installed program needs is on this PC so it can be bundled:
  * the openWakeWord models ("hey jarvis" + its feature models)   - REQUIRED
  * MediaPipe's hand_landmarker.task for hand mouse               - optional (the app
    downloads it itself on first use if it isn't bundled)
"""
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
VCREDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
HAND_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)


def main() -> int:
    import openwakeword
    import config

    print("Downloading wake-word models (skipped if already present)...")
    try:
        openwakeword.utils.download_models()
    except Exception as e:  # offline is fine as long as the files are already on disk (checked below)
        print(f"WARNING: model download step failed ({e}); checking for existing files...")

    models_dir = Path(openwakeword.__file__).resolve().parent / "resources" / "models"
    wake_path = Path(openwakeword.MODELS[config.WAKE_WORD]["model_path"])
    wake_ok = wake_path.exists() or wake_path.with_suffix(".onnx").exists()
    feature_ok = all((models_dir / n).exists() for n in ("melspectrogram.onnx", "embedding_model.onnx"))
    if not (wake_ok and feature_ok):
        print("\nERROR: wake-word model files are missing from", models_dir)
        for p in sorted(models_dir.glob("*")):
            print("   found:", p.name)
        return 1
    print("Wake-word models OK:", ", ".join(sorted(p.name for p in models_dir.glob("*") if p.is_file())))

    target = HERE / "hand_landmarker.task"
    if target.exists():
        print("Hand-tracking model already present.")
    else:
        print("Downloading the hand-tracking model (~8 MB)...")
        try:
            urllib.request.urlretrieve(HAND_URL, target)
            print("Hand-tracking model downloaded.")
        except Exception as e:  # not fatal: the installed app can fetch it on first use
            if target.exists():
                target.unlink()
            print(f"WARNING: couldn't download it now ({e}).")
            print("         The installer will still work; hand mouse will download it on first use.")

    # Microsoft's Visual C++ runtime: many clean Windows PCs lack it and the speech/hand-tracking
    # libraries need it. If it is bundled, the installer adds it automatically when missing.
    redist = HERE / "redist" / "vc_redist.x64.exe"
    if redist.exists() and redist.stat().st_size > 10_000_000:
        print("Microsoft Visual C++ runtime installer already present.")
    else:
        print("Downloading the Microsoft Visual C++ runtime installer (~25 MB)...")
        try:
            redist.parent.mkdir(exist_ok=True)
            urllib.request.urlretrieve(VCREDIST_URL, redist)
            if redist.stat().st_size < 10_000_000:
                raise RuntimeError("download looks incomplete")
            print("Visual C++ runtime installer downloaded.")
        except Exception as e:  # not fatal, but the installer then can't repair a PC that lacks it
            if redist.exists():
                redist.unlink()
            print(f"WARNING: couldn't download it ({e}).")
            print("         The installer will still be built, but it won't install the runtime on PCs without it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

import os, shutil, subprocess, sys, threading, venv, webbrowser
from pathlib import Path

here = Path(__file__).resolve().parent
if not shutil.which("git"):
    sys.exit("Git is not installed or not on PATH. Install it from https://git-scm.com and run again.")

vd = here / ".venv"
py = vd / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
if not py.exists():
    print("Creating virtual environment...")
    venv.create(vd, with_pip=True)
req, stamp = here / "requirements.txt", vd / ".installed"
if not stamp.exists() or stamp.stat().st_mtime < req.stat().st_mtime:
    print("Installing requirements...")
    subprocess.check_call([str(py), "-m", "pip", "install", "-q", "-r", str(req)])
    stamp.touch()

port = int(os.environ.get("PORT", 8765))
url = f"http://127.0.0.1:{port}"
threading.Timer(1.5, lambda: webbrowser.open(url)).start()
print(f"GitScope running at {url}  (Ctrl+C to stop)")
subprocess.call([str(py), "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port)], cwd=here)

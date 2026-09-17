import subprocess
import sys


def opensportslib_installed():
    try:
        import opensportslib
        return True
    except ImportError:
        return False


def gpu_available():
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


def install_opensportslib():
    subprocess.check_call([
        sys.executable,
        "-m",
        "pip",
        "install",
        "opensportslib",
    ])


def setup_opensportslib():
    subprocess.check_call([
        "opensportslib",
        "setup",
    ])


def ensure_opensportslib_environment():

    if not opensportslib_installed():
        print("OpenSportsLib not found. Installing...")
        install_opensportslib()

    if gpu_available():
        print("GPU detected.")

        print("Checking OpenSportsLib GPU setup...")
        setup_opensportslib()

    else:
        print("No GPU detected. Skipping GPU setup.")
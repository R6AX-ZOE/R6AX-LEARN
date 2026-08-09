import os
import subprocess
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

print("Compiling translation files...")

try:
    result = subprocess.run(
        [sys.executable, "-m", "babel.messages.frontend", "compile", "-d", "app/i18n/locales"],
        capture_output=True,
        text=True,
        cwd=ROOT_DIR,
    )
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)
    print("Return code:", result.returncode)
except Exception as e:
    print(f"Error: {e}")

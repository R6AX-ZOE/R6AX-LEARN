import subprocess
import sys

print("Compiling translation files...")

try:
    result = subprocess.run(
        [sys.executable, "-m", "babel.messages.frontend", "compile", "-d", "app/i18n/locales"],
        capture_output=True,
        text=True,
        cwd="E:\_Victor_Programming\_Victor_AiAssisted\R6AX-LEARN"
    )
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)
    print("Return code:", result.returncode)
except Exception as e:
    print(f"Error: {e}")
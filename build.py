"""Build script to package Claude Usage Widget into a single .exe using PyInstaller."""

import subprocess
import sys

def main():
    args = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--noconsole",
        "--name", "ClaudeUsageWidget",
        "--icon", "new_icon.ico",
        # Hidden imports that PyInstaller may not detect automatically
        "--hidden-import", "pystray",
        "--hidden-import", "pystray._win32",
        "--hidden-import", "PIL",
        "--hidden-import", "PIL.Image",
        "--hidden-import", "PIL.ImageDraw",
        "--hidden-import", "PIL.ImageFont",
        "--hidden-import", "win11toast",
        "claude_usage_menubar.py",
    ]

    print("Running PyInstaller...")
    print(" ".join(args))
    result = subprocess.run(args)

    if result.returncode == 0:
        print("\nBuild successful! Output: dist/ClaudeUsageWidget.exe")
    else:
        print(f"\nBuild failed with exit code {result.returncode}")
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""打包成单文件 exe（产物就在 labeler\\英雄标注工具.exe）

    python build.py

注意：exe 必须和 ..\\data 同级目录结构保持（exe 在 jcc_s18\\labeler\\ 下），
英雄图标、标注记录都从 jcc_s18\\data 读，不打进 exe。
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
NAME = "英雄标注工具"


def main():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--onefile", "--windowed",
        "--name", NAME,
        "--distpath", str(HERE),
        "--workpath", str(HERE / "build" / "_work"),
        "--specpath", str(HERE / "build"),
        "--paths", str(ROOT / "core"),
        "--hidden-import", "board_units",
        "--hidden-import", "hero_names",
        "--collect-submodules", "scipy.ndimage",
        "--exclude-module", "matplotlib",
        "--exclude-module", "rapidocr_onnxruntime",
        "--exclude-module", "cv2",
        str(HERE / "app.py"),
    ]
    print(" ".join(cmd))
    r = subprocess.run(cmd)
    if r.returncode != 0:
        sys.exit(r.returncode)
    exe = HERE / (NAME + ".exe")
    print("\n完成:", exe, "%.1f MB" % (exe.stat().st_size / 1024 / 1024))


if __name__ == "__main__":
    main()

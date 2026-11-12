#!/usr/bin/env python3
"""見積もり結果の保存先パスを決めるスクリプト

Git リポジトリのルートと同じ階層に docs/ フォルダを作り（なければ作成）、
「YYYYMMDD_工数見積もり_<対応内容>.md」形式のパスを出力する。

    project/          ← Git 管理外
    ├── repo/         ← Git リポジトリ（ここで実行）
    └── docs/         ← ここに保存

使い方:
    python3 output_path.py "<対応内容>"
出力（1行目: Markdown のパス、2行目: tasks.json のパス）
"""
from __future__ import annotations

import datetime
import re
import subprocess
import sys
from pathlib import Path

MAX_LABEL_LEN = 40


def sanitize(label: str) -> str:
    # ファイル名に使えない文字・空白を置き換える
    label = re.sub(r'[\\/:*?"<>|\s]+', "-", label.strip())
    label = re.sub(r"-{2,}", "-", label).strip("-.")
    return label[:MAX_LABEL_LEN] or "改修"


def main() -> None:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        sys.exit('使い方: python3 output_path.py "<対応内容>"')

    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        sys.exit("エラー: Git リポジトリ内で実行してください（保存先を決められません）")

    docs = Path(top).resolve().parent / "docs"
    docs.mkdir(parents=True, exist_ok=True)

    date = datetime.date.today().strftime("%Y%m%d")
    stem = f"{date}_工数見積もり_{sanitize(sys.argv[1])}"

    # 同名ファイルがあれば _2, _3 ... を付ける（既存の見積もりを上書きしない）
    candidate, n = stem, 2
    while (docs / f"{candidate}.md").exists():
        candidate = f"{stem}_{n}"
        n += 1

    print(docs / f"{candidate}.md")
    print(docs / f"{candidate}.tasks.json")


if __name__ == "__main__":
    main()

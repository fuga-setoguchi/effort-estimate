#!/usr/bin/env python3
"""見積もり結果の保存先パスを決めるスクリプト

保存先フォルダは次の順で決まる（なければ作成する）。

  1. 引数 --dir で指定したフォルダ
  2. 環境変数 EFFORT_ESTIMATE_OUTPUT_DIR で指定したフォルダ
  3. 既定: Git リポジトリのルートと同じ階層の docs/

    project/          ← Git 管理外
    ├── repo/         ← Git リポジトリ（ここで実行）
    └── docs/         ← 既定ではここに保存

1 か 2 で指定した場合は、Git リポジトリの外でも実行できる。
ファイル名は「YYYYMMDD_工数見積もり_<対応内容>.md」形式になる。

使い方:
    python3 output_path.py "<対応内容>" [--dir <保存先フォルダ>]
出力（1行目: Markdown のパス、2行目: tasks.json のパス）
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import subprocess
import sys
from pathlib import Path

MAX_LABEL_LEN = 40
ENV_VAR = "EFFORT_ESTIMATE_OUTPUT_DIR"


def sanitize(label: str) -> str:
    # ファイル名に使えない文字・空白を置き換える
    label = re.sub(r'[\\/:*?"<>|\s]+', "-", label.strip())
    label = re.sub(r"-{2,}", "-", label).strip("-.")
    return label[:MAX_LABEL_LEN] or "改修"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def repo_root() -> Path:
    """メインのリポジトリのルートを返す。

    worktree 内で実行した場合も、worktree ではなく元のリポジトリを返す
    （worktree はリポジトリの中に作られることがあり、その親に docs/ を
    作るとリポジトリを汚してしまうため）。
    """
    top = Path(git("rev-parse", "--show-toplevel")).resolve()
    common = Path(git("rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = Path.cwd() / common
    common = common.resolve()
    # 通常のリポジトリと worktree では <メインのリポジトリ>/.git を指す
    if common.name == ".git":
        return common.parent
    return top


def resolve_dir(arg_dir: str | None) -> Path:
    chosen = arg_dir or os.environ.get(ENV_VAR, "").strip()
    if chosen:
        return Path(chosen).expanduser().resolve()
    try:
        return repo_root().parent / "docs"
    except (subprocess.CalledProcessError, FileNotFoundError):
        sys.exit(
            "エラー: Git リポジトリの外では保存先を決められません。"
            f"--dir <保存先フォルダ> か環境変数 {ENV_VAR} で保存先を指定してください"
        )


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="見積もり結果の保存先パスを決める")
    ap.add_argument("label", help="対応内容（ファイル名に使う短い説明）")
    ap.add_argument("--dir", help=f"保存先フォルダ（省略時は環境変数 {ENV_VAR}、なければ既定の docs/）")
    args = ap.parse_args()

    if not args.label.strip():
        sys.exit('使い方: python3 output_path.py "<対応内容>" [--dir <保存先フォルダ>]')

    docs = resolve_dir(args.dir)
    if docs.exists() and not docs.is_dir():
        sys.exit(f"エラー: 保存先がフォルダではありません: {docs}")
    try:
        docs.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        sys.exit(f"エラー: 保存先フォルダを作成できません ({docs}): {e}")

    date = datetime.date.today().strftime("%Y%m%d")
    stem = f"{date}_工数見積もり_{sanitize(args.label)}"

    # 同名ファイルがあれば _2, _3 ... を付ける（既存の見積もりを上書きしない）。
    # tasks.json は .md より先に作られるので、両方を見て判定する。
    candidate, n = stem, 2
    while (docs / f"{candidate}.md").exists() or (docs / f"{candidate}.tasks.json").exists():
        candidate = f"{stem}_{n}"
        n += 1

    print(docs / f"{candidate}.md")
    print(docs / f"{candidate}.tasks.json")


if __name__ == "__main__":
    main()

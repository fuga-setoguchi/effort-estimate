#!/usr/bin/env python3
"""工数計算スクリプト

tasks.json（Claude が作成したタスク分類）と estimation_rules.json（基準表）から
実作業見込み（AI支援あり）と対外工数（従来基準）を計算し、Markdown で出力する。

使い方:
    python3 calc.py tasks.json [--rules path/to/estimation_rules.json] [--json]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

DEFAULT_RULES = Path(__file__).resolve().parent.parent / "references" / "estimation_rules.json"
SIZES = ("S", "M", "L")


def ceil_step(value: float, step: float) -> float:
    """step 単位で切り上げる（浮動小数の誤差を吸収）。"""
    return math.ceil(round(value / step, 6)) * step


def fmt(value: float) -> str:
    return f"{value:g}"


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.exit(f"エラー: ファイルが見つかりません: {path}")
    except json.JSONDecodeError as e:
        sys.exit(f"エラー: JSON の形式が正しくありません ({path}): {e}")


def calc_task(task: dict, rules: dict, errors: list[str]) -> dict | None:
    tid = task.get("id", "?")
    coef_rules = rules["coefficients"]
    step = rules["rounding_step"]

    # 補正係数
    coef = 1.0
    coef_detail = {}
    for key, table in coef_rules.items():
        level = task.get(key)
        if level not in table:
            errors.append(f"[{tid}] {key} の値が不正です: {level!r}（候補: {', '.join(table)}）")
            return None
        coef *= table[level]
        coef_detail[key] = level

    ttype = task.get("type")
    if ttype == "custom":
        try:
            o, m, p = (float(task[k]) for k in ("optimistic", "likely", "pessimistic"))
        except (KeyError, TypeError, ValueError):
            errors.append(f"[{tid}] custom には optimistic / likely / pessimistic（数値）が必要です")
            return None
        if not (o <= m <= p):
            errors.append(f"[{tid}] 三点見積もりは 楽観 <= 標準 <= 悲観 にしてください")
            return None
        phase = task.get("phase")
        if phase not in rules["phases"]:
            errors.append(f"[{tid}] custom には phase が必要です（候補: {', '.join(rules['phases'])}）")
            return None
        base_actual = (o + 4 * m + p) / 6
        base_trad = base_actual * rules["custom_traditional_ratio"]
        label = "custom（三点見積もり）"
        size = "-"
    else:
        wt = rules["work_types"].get(ttype)
        if wt is None:
            errors.append(f"[{tid}] 未定義の作業種別です: {ttype!r}")
            return None
        size = task.get("size")
        if size not in SIZES:
            errors.append(f"[{tid}] size は S / M / L のいずれかにしてください: {size!r}")
            return None
        base_actual = wt["actual"][size]
        base_trad = wt["traditional"][size]
        phase = wt["phase"]
        label = wt["label"]

    return {
        "id": tid,
        "name": task.get("name", ""),
        "type": ttype,
        "type_label": label,
        "size": size,
        "phase": phase,
        "coefficient": round(coef, 4),
        "coef_detail": coef_detail,
        "actual": ceil_step(base_actual * coef, step),
        "traditional": ceil_step(base_trad * coef, step),
        "reason": task.get("reason", ""),
        "evidence": task.get("evidence", []),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="工数計算")
    ap.add_argument("tasks", type=Path)
    ap.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    ap.add_argument("--json", action="store_true", help="結果を JSON で出力する")
    args = ap.parse_args()

    rules = load_json(args.rules)
    data = load_json(args.tasks)
    step = rules["rounding_step"]
    hpd = rules["hours_per_day"]

    errors: list[str] = []
    warnings: list[str] = []

    risk = data.get("project_risk")
    if risk not in rules["buffer_rate"]:
        errors.append(f"project_risk の値が不正です: {risk!r}（候補: {', '.join(rules['buffer_rate'])}）")

    tasks = data.get("tasks") or []
    if not tasks:
        errors.append("tasks が空です")

    ids = [t.get("id") for t in tasks]
    if len(ids) != len(set(ids)):
        errors.append("タスクの id が重複しています")

    results = [r for t in tasks if (r := calc_task(t, rules, errors)) is not None]

    if errors:
        print("計算できませんでした。tasks.json を修正してください。", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    # 必須工程のチェック
    skipped = data.get("skipped_phases", {})
    present = {r["phase"] for r in results}
    for ph in rules["required_phases"]:
        if ph not in present and ph not in skipped:
            warnings.append(
                f"必須工程「{rules['phases'][ph]}」のタスクがありません。"
                f"不要なら skipped_phases に理由を書いてください。"
            )

    # 集計
    sub_actual = sum(r["actual"] for r in results)
    sub_trad = sum(r["traditional"] for r in results)
    rate = rules["buffer_rate"][risk]
    buf_actual = ceil_step(sub_actual * rate, step)
    # バッファは「想定外の作業に備えた予備の時間」。実際に対応するのは AI 支援ありの体制なので、
    # 実作業見込みで算出したバッファの時間を、そのまま対外工数にも保険として載せる。
    buf_trad = buf_actual
    total_actual = sub_actual + buf_actual
    total_trad = sub_trad + buf_trad

    custom_actual = sum(r["actual"] for r in results if r["type"] == "custom")
    threshold = rules["warnings"]["custom_ratio_threshold"]
    if sub_actual and custom_actual / sub_actual > threshold:
        warnings.append(
            f"custom タスクが実作業見込みの {custom_actual / sub_actual:.0%} を占めています"
            f"（目安 {threshold:.0%} 以下）。既存の作業種別に寄せられないか見直してください。"
        )

    by_phase = []
    for ph, ph_label in rules["phases"].items():
        a = sum(r["actual"] for r in results if r["phase"] == ph)
        t = sum(r["traditional"] for r in results if r["phase"] == ph)
        by_phase.append({"phase": ph, "label": ph_label, "actual": a, "traditional": t})

    summary = {
        "rules_version": rules.get("version"),
        "project_risk": risk,
        "buffer_rate": rate,
        "subtotal": {"actual": sub_actual, "traditional": sub_trad},
        "buffer": {"actual": buf_actual, "traditional": buf_trad},
        "total": {"actual": total_actual, "traditional": total_trad},
        "total_days": {
            "actual": round(total_actual / hpd, 2),
            "traditional": round(total_trad / hpd, 2),
        },
        "hours_per_day": hpd,
        "by_phase": by_phase,
        "tasks": results,
        "skipped_phases": skipped,
        "warnings": warnings,
    }

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    out = []
    out.append("### 工数サマリ\n")
    out.append("| 項目 | 実作業見込み（AI支援あり） | 対外工数（従来基準） |")
    out.append("|---|---|---|")
    out.append(f"| 小計 | {fmt(sub_actual)}h | {fmt(sub_trad)}h |")
    out.append(
        f"| バッファ（保険・{risk}: 実作業小計の{rate:.0%}） | {fmt(buf_actual)}h | {fmt(buf_trad)}h（実作業と同じ時間） |"
    )
    out.append(f"| **合計** | **{fmt(total_actual)}h** | **{fmt(total_trad)}h** |")
    out.append(
        f"| 人日換算（{fmt(hpd)}h/日） | {summary['total_days']['actual']:g}人日 "
        f"| {summary['total_days']['traditional']:g}人日 |"
    )
    out.append("")
    out.append("### 工程別内訳\n")
    out.append("| 工程 | 実作業見込み | 対外工数 |")
    out.append("|---|---|---|")
    for p in by_phase:
        out.append(f"| {p['label']} | {fmt(p['actual'])}h | {fmt(p['traditional'])}h |")
    if skipped:
        out.append("")
        out.append("計上しなかった工程：")
        for ph, why in skipped.items():
            out.append(f"- {rules['phases'].get(ph, ph)}：{why}")
    out.append("")
    out.append("### タスク明細\n")
    out.append("| ID | タスク | 作業種別 | サイズ | 係数 | 実作業 | 対外 |")
    out.append("|---|---|---|---|---|---|---|")
    for r in results:
        cd = r["coef_detail"]
        coef_str = f"{r['coefficient']:g}（不確実性:{cd['uncertainty']} / 複雑さ:{cd['complexity']} / 未経験:{cd['unfamiliarity']}）"
        out.append(
            f"| {r['id']} | {r['name']} | {r['type_label']} | {r['size']} | {coef_str} "
            f"| {fmt(r['actual'])}h | {fmt(r['traditional'])}h |"
        )
    if warnings:
        out.append("")
        out.append("### 計算時の警告\n")
        for w in warnings:
            out.append(f"- ⚠️ {w}")
    out.append("")
    out.append(f"<sub>基準表 v{rules.get('version')} で算出</sub>")
    print("\n".join(out))


if __name__ == "__main__":
    main()

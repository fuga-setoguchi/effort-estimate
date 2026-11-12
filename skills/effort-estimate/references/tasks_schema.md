# tasks.json の書き方

`scripts/calc.py` に渡すファイルの形式。記入例は `assets/example_tasks.json`（基本）と `assets/example_tasks_custom.json`（custom タスクと計上しない工程を含む例）にある。

形式が正しくない場合、calc.py は計算せずにエラーの内容を表示して終了する。

## 全体

| 項目 | 必須 | 内容 |
|---|---|---|
| `title` | 任意 | 改修のタイトル。計算には使わない |
| `project_risk` | 必須 | 案件全体のリスク。`low` / `mid` / `high` |
| `skipped_phases` | 任意 | 計上しない工程と、その理由（下記） |
| `tasks` | 必須 | タスクの配列。1件以上 |

## skipped_phases（計上しない工程）

必須工程のうち、タスクを1件も計上しないものを `"工程名": "理由"` の形で書く。書かないと calc.py が警告を出す。理由は見積もり結果の「前提条件」にも書く。

工程名は次の5つ。

| 工程名 | 意味 |
|---|---|
| `investigation` | 調査・設計 |
| `implementation` | 実装 |
| `test` | テスト |
| `review` | レビュー・修正 |
| `release` | リリース・確認 |

```json
"skipped_phases": {
  "release": "本番へのデプロイと本番確認は先方のインフラ担当が実施するため計上しない"
}
```

計上しない工程がなければ `{}` にするか、項目ごと省く。

## タスク（共通の項目）

| 項目 | 必須 | 内容 |
|---|---|---|
| `id` | 必須 | タスクの番号（`T1` など）。重複不可 |
| `name` | 必須 | タスク名 |
| `type` | 必須 | 作業種別。`estimation_rules.json` の `work_types` にある名前か、`custom` |
| `uncertainty` | 必須 | 仕様の不確実性。`low` / `mid` / `high` |
| `complexity` | 必須 | 既存コードの複雑さ。`low` / `mid` / `high` |
| `unfamiliarity` | 必須 | 未経験の技術・領域。`none` / `partial` / `new` |
| `reason` | 必須 | そのサイズ・係数にした理由。空だと calc.py が警告を出す |
| `evidence` | 任意 | 調査で確認したファイルパスの配列 |

## 基準表の作業種別を使うタスク

共通の項目に加えて、`size`（`S` / `M` / `L`）を書く。工程は作業種別から自動で決まる。

```json
{
  "id": "T3",
  "name": "一覧APIにステータス絞り込みを追加",
  "type": "api_endpoint",
  "size": "S",
  "uncertainty": "mid",
  "complexity": "mid",
  "unfamiliarity": "none",
  "reason": "既存の日付絞り込みと同じパターンで追加できるためS",
  "evidence": ["app/Http/Requests/OrderIndexRequest.php"]
}
```

## custom タスク

どの作業種別にも当てはまらない作業だけに使う。`size` の代わりに次の4つを書く。

| 項目 | 内容 |
|---|---|
| `phase` | 工程名（上の5つのどれか）。custom は工程が自動で決まらないので必須 |
| `optimistic` | 楽観の時間（AI 支援あり、単位は時間） |
| `likely` | 標準の時間 |
| `pessimistic` | 悲観の時間 |

3つの時間は 0 以上で、楽観 ≦ 標準 ≦ 悲観 にする。

```json
{
  "id": "T2",
  "name": "匿名化対象の項目一覧（先方の法務確認用）の作成",
  "type": "custom",
  "phase": "investigation",
  "optimistic": 1,
  "likely": 2,
  "pessimistic": 4,
  "uncertainty": "mid",
  "complexity": "low",
  "unfamiliarity": "none",
  "reason": "先方の法務に渡す確認資料で、基準表に当てはまる種別がない",
  "evidence": []
}
```

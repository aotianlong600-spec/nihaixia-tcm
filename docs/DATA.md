# 方剂索引数据说明

## 文件

`app/resources/open_formula_library.json`（约 912 KB，2 空格缩进）

| 顶层键 | 内容 |
|---|---|
| `formulas` | 314 首方：`id`、`name`、`syndrome`、`components`（`name`、`processing`、`source_dose`、`source_unit`、`source_ref`）、`contraindications`、`modification_notes`、`source_refs`、`keywords` |
| `patterns` | 315 条证型规则：`id`、`formula_id`、`name`、`syndrome`、`required`、`reference`、`source_refs` |
| `source_metadata` | 上游项目、提交、许可（Apache-2.0）与说明 |

药味共 1,635 条。来源与转换说明见 `app/resources/来源说明.md`，许可全文在 `licenses/nihaixia-app-APACHE-2.0.txt`。

## 已删除的字段

### `six_meridian`（六经归经）

2026-11 按所有者决定删除，等重构后按新 schema 重新引入。删除原因：

- 314 方与 315 条规则全部带此字段，但取值有 49 种写法，标准六经只占其中 6 种
- 单一六经仅 149 方，其余 162 方是 `太阴/胃`、`阳明/厥阴` 这类复合写法，另有 3 条是 `外用`
- 复合值里混进 20 处非六经内容：肝、心、肺、膀胱、脾、胃、肠、血分、金匮、外用
- 90 条规则的归经与所属方剂互不包含（例：小建中汤 规则标`太阳`、方剂标`太阴`）
- 检索从未支持该字段：`q=太阴` 只能命中 3 条，实际带此标签的有 100 方

数据里已按行删除 629 行（314 + 315），其余字节未变。`library/formulas.json` 从未包含该字段，未受影响。

重构时要补的：六经枚举与归一（六经列表 + 兼证列表分列）、检索参数 `six_meridian=`、入库校验、90 条冲突的裁决口径。辨证本身（传变、提纲证、欲解时、治法）不在本仓库范围内。

## 数据边界

- 炮制字段多为未知；药名未拆炮制信息
- `source_dose` 为原文剂量字符串，未做单位换算，不可直接当临床用量
- `keywords` 是检索参考，不是必选方证
- 医学准确性、剂量与禁忌未经独立核验

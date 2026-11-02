# 数据与资产

## 运行期依赖

| 路径 | 数量 | 被谁使用 | 说明 |
|---|---:|---|---|
| `data/HeroData.json` | 65 英雄 | `scan.py` | 商店名单交叉核对；UTF-8 |
| `data/equipment_s18/` | 139 图标 | `board_units` / `item_bench` | 装备模板，文件名=装备名 |
| `data/augmenticons_s18/` | 256 图标 | `augments` | 强化符文官方原画，文件名=符文名 |
| `data/augmenticons_ingame/` | 1 图标 | `augments` | 游戏内截图模板，同名覆盖原画 |
| `data/augmenticons_s18_index.json` | — | `augments` | 文件名 → `{hexId, rarity, 回合, 描述}` |
| `data/hero_names_cache.json` | — | `hero_names` | `--names` 缓存，可删可重建 |
| `data/heroicons_s18/` | 65 图标 | `labeler` | 标注器右侧头像，文件名=英雄名 |
| `data/hero_labels/` | 12 条标注 | `hero_match` / `labeler` | **用户标注数据，勿删** |
| `data/s18db/comps.json` 等 | 27 套阵容 / 65 英雄 / 36 羁绊 / 151 装备 / 256 符文 | `recommend.py` | 推荐器运行时索引；扫描器本身不读 |

## 静态/辅助数据

| 路径 | 说明 |
|---|---|
| `data/EquipmentData.json` | 装备合成路径；`tools/build_s18db.py` 用它 enrichment，扫描运行时不读 |
| `data/sheet_s18.png` | 65 英雄图标编号对照表，人眼用 |
| `data/s18_index.txt` | 图标编号 → 英雄名，人眼用 |
| `data/s18_herodata.txt` | `HeroData.json` 的可读版 |
| `data/s18db/` | S18 静态知识库，详见 [s18db](s18db.md) |
| `config/strategy_rules.json` | 推荐器的等级/存钱/搜牌参数（不是数据事实） |

## 本次清理（2026-11-02）

按「深度清理」移出仓库、备份在：

```
C:\Users\feng1\AppData\Local\Temp\jcc_s18_cleanup_20261102\
```

| 移出项 | 体积 | 原因 | 影响 |
|---|---:|---|---|
| `data/s18db/raw/` | 8.3 MB | 重建静态库的原始导出，运行时不读 | 离线重建前需恢复备份或重新抓取 |
| `data/s18db/images/` | 9.8 MB | 与 `data/augmenticons_s18/` 大量重复 | `augments.json.iconFile` 指向的图片缺失；扫描器不受影响 |
| `output/` 未引用调试产物 | 25.5 MB | 实验截图/中间 JSON | 文档引用的样例与 `crops_sample/` 已保留 |
| 根目录 `_augarea.png` | 0.35 MB | 调试裁剪 | 无 |
| 根目录 `sol.py` | — | 临时调试脚本 | 无 |

备份目录里的 `_manifest.json` 记录了所有移动项。确认不需要后可手动删除整个备份目录。

## 数据来源

- 英雄图标 / S18 英雄数据：`XJYdemons/JinChanChanTool` 的 `Resources/HeroDatas/S18/`。
- 静态库：`jcc.datatft.com`（阵容、资料库、评级、仙灵规则、概率表）+ `dataj.cc/hex`（符文统计）。
- 详细来源与版本见 [data/s18db/INDEX.md](../data/s18db/INDEX.md)。

## 更新图标

### 新增装备

1. 把图标命名为 `<装备名>.png` 放入 `data/equipment_s18/`。
2. 保证 56×56 可缩放；匹配会统一缩放并去 2px 黑边。
3. 跑一张带该装备的截图，确认 `score >= 0.55`。

### 新增强化符文

1. 官方原画放 `data/augmenticons_s18/<符文名>.png`（透明底）。
2. 游戏内截图放 `data/augmenticons_ingame/<符文名>.png`（同名优先）。
3. 在 `data/augmenticons_s18_index.json` 补 `hexId/rarity/回合/描述`。
4. 首次运行会重建掩膜，约 1.6s。

### 新增英雄头像（标注器）

把 `<英雄名>.png` 放入 `data/heroicons_s18/`；标注器右侧会显示。

## 注意

- 所有 JSON/源码都是 UTF-8；PowerShell 默认编码可能显示乱码，不要据此改文件。
- `data/hero_labels/` 是人工成果，不随清理删除。
- `data/hero_names_cache.json` 可删；删后 `--names` 会重新请求 VLM。
- `data/s18db/images/` 已移出，`core/augments.py` 不需要它；不要为了「补全 s18db」把它加回扫描依赖。

## 相关文档

- [s18db](s18db.md)
- [modules/augments](modules/augments.md)
- [modules/hero-names](modules/hero-names.md)
- [development](development.md)

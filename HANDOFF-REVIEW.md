# Tokenof — 複查 Handoff（待確認細節）

> 2026-08-13｜狀態：**Dashboard 已完成、可閱讀、真實資料正常渲染**
> 本文件記錄「已完成的進度」+「後續要細問並更新的細節」。
> 使用者已確認 dashboard 看得到了（「終於，讚」）。

---

## 一、目前完成狀態

| 項目 | 狀態 |
|---|---|
| DeepSeek / Claude Code / Codex 三來源資料擷取 | ✅ 完成 |
| 架構拆分（build.py + collectors/） | ✅ 完成 |
| Dashboard v2（來源篩選/年-月-日/MTD 對比/洞察） | ✅ 完成 |
| 去 CDN（Chart.js 本地 + 手寫 CSS） | ✅ 完成 |
| 資料容器順序修正（P0-1b） | ✅ 完成 |
| 真實資料渲染驗證（headless Chrome） | ✅ 通過 |

**使用方式**：`python build.py --sources all --days 90` → 瀏覽器打開 `tokenof-dashboard.html`。

---

## 二、待確認細節（使用者要再細問）

### 🔴 1. 費用計價單位：CNY → NTD

**現況**：DeepSeek API 回傳人民幣（CNY），dashboard 目前顯示 `¥` + CNY 金額。

**要確認**：
- 是否全部換算成**新台幣 NTD**？還是 CNY / NTD 並列？
- 換算匯率來源與數值？（即時匯率 vs 固定匯率，誰維護 `pricing.json` 或換算常數）
- Claude Code / Codex 是訂閱制（無實際扣款），換算成 NTD 後如何標示「非實際支出」？

**影響範圍**：
- `collectors/deepseek.py`：cost 欄位（現在是 CNY 原值）
- `tokenof-dashboard.html`：`fmtCny()`、摘要卡「實際花費」、MoM 花費對比、模型花費表
- `build.py` / schema：`currency` 欄位目前硬編 CNY

### 🟡 2. Cache 命中率的精確意義

**現況**：`cache_hit_rate = hit / (hit + miss)`，即「命中快取的 input token 佔所有 input token 比例」。

**要確認**：
- 這個定義是否符合使用者直覺？（有些產品把命中率定義為「命中請求數 / 總請求數」，而不是 token 比例）
- 是否需要同時顯示「token 層級命中率」和「請求層級命中率」兩種？

### 🟡 3. 「命中率對比」卡片的意義

**現況**：MoM 卡片裡有一張「命中率對比」，顯示本月 vs 上月的命中率差異（單位 pp，百分比點）。

**要確認**：
- 這張卡對使用者有沒有價值？還是改成「命中率絕對值 + 趨勢箭頭」更直觀？
- 命中率「上升 = 好」（綠色）的顏色語意是否正確？（目前已改成 up=綠、down=紅）

### 🟡 4. 其他指標定義要逐一確認

| 指標 | 現況定義 | 待確認 |
|---|---|---|
| 「總 Token」 | hit + miss + response（跨 3 來源加總） | 跨來源加總是否合理？DeepSeek(CNY) + Claude Code(USD) 的 token 直接相加有意義嗎？ |
| 「實際花費」 | 只算 DeepSeek（currency=CNY） | 訂閱制的 Claude Code/Codex 是否要顯示「等值估算」？ |
| 「API 請求數」 | 各來源 request_count 加總 | Claude Code 是去重後請求數、Codex 是輪次數、DeepSeek 是 REQUEST type，三者語意不同，加總是否誤導？ |
| MTD 對比 | 本月到第 N 天 vs 上月同樣前 N 天 | 已做，確認符合預期 |

---

## 三、技術待辦（次要，可後做）

- [ ] `pricing.json` 尚未建立（訂閱制定價表，供 Claude Code/Codex 換算「等值估算」）
- [ ] Codex 額度卡：`used_percent` 目前 4%，`resets_at` 顯示絕對時間，可能要改「剩餘天數倒數」
- [ ] `usage_data.json` 已 gitignore、HTML 資料容器空樣板（防真實用量外洩）——已處理

---

## 四、檔案清單

| 檔案 | 說明 |
|---|---|
| `build.py` | 主入口（合併來源 + 注入 HTML） |
| `collectors/deepseek.py` | DeepSeek API（CNY, metered） |
| `collectors/claude_code.py` | 本機 jsonl（USD, unknown） |
| `collectors/codex.py` | 本機 jsonl（USD, unknown + 額度） |
| `tokenof-dashboard.html` | 自包含 dashboard（資料由 build.py 注入） |
| `chart.umd.min.js` | 本地 Chart.js |
| `HANDOFF-CC-2026-08-10.md` | Claude Code 原始審查 |
| `MULTI-SOURCE.md` | 多來源整合規格 |

---

*待使用者細問後，逐項確認並更新 dashboard。*

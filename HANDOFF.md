# Tokenof Handoff — 2026-08-10

> **給 Claude Code**：請審查並修復以下問題。專案在 `D:\Coding\tokenof\`，GitHub: `redmoon30/tokenof`。
>
> ⚠️ **2026-08-10 已審查完畢 → 回覆與待辦順序見 [`HANDOFF-CC-2026-08-10.md`](HANDOFF-CC-2026-08-10.md)。**
> 本文下方的「已知問題」清單反映的是 commit `24881c4`（資料嵌入）**之前**的狀態；
> 該 commit 引入了一個更嚴重的結構性錯誤（資料 script 被巢狀進外層 script，整個 JS 解析失敗），
> 在修好它之前，下方 #2 描述的圖表行為都觀察不到。**請以 CC 那份的優先序為準。**

---

## 專案目的

取代 DeepSeek 官方難讀的用量圖表 (https://platform.deepseek.com/usage)，做一個簡單清晰的本機 Dashboard。

## 架構

```
fetch_usage.py ──(1)──▶ usage_data.json ──(2)──▶ tokenof-dashboard.html
       │                        │                        │
  從 platform API         JSON 快取              自包含 HTML
  拉用量資料                                    Chart.js 圖表
       │                                             │
       └──────────(3) 資料嵌入 HTML ◀────────────────┘
```

三種資料載入路徑：
1. **嵌入**：`<script id="tokenof-data" type="application/json">{...}</script>` — fetch_usage.py 注入，`file://` 直接可用
2. **Fetch fallback**：`fetch('usage_data.json')` — local server 模式
3. **Mock**：`python fetch_usage.py --mock` — 測試用假資料

---

## 已知問題

### 🔴 Critical

#### 1. HTML 資料注入不可重複執行（fetch_usage.py:330）
```python
html_content = html_content.replace("// TOKENOF_DATA_PLACEHOLDER", data_script)
```
第一次執行後 `// TOKENOF_DATA_PLACEHOLDER` 被取代為 `<script id="tokenof-data">...</script>`。
第二次執行時 placeholder 已不存在 → `replace` 無作用 → **HTML 中的資料永遠是第一次的舊資料**。

**Expected**: 每次執行 fetch_usage.py 都應更新 HTML 中的嵌入資料。
**Fix approach**: 用 regex 找出並取代既有的 `<script id="tokenof-data"...>...</script>` 區塊，而非依賴一次性 placeholder。

#### 2. 年/月/日檢視資料粒度不一致（tokenof-dashboard.html）

| 按鈕 | renderMonthlyChart | renderDailyChart | 問題 |
|---|---|---|---|
| 年 | 按月彙總 ✓ | 仍顯示每日 ✗ | 365 天每日 bar 不可讀 |
| 月 | 按月彙總（1-2月） | 仍顯示每日 | 標題寫「每週」但資料未按週彙總 |
| 日 | 按月彙總（1月） | 每日 ✓ | 左圖只有1根 bar，無意義 |

- `getGroupedByDay` 永遠回傳每日資料，`renderDailyChart` 永遠吃每日資料，無視 currentView。
- `getDaysInView` 在 'month' 模式只取近 30 天，但 `getGroupedByMonth` 只能產出 1-2 個月。
- 需要 `getGroupedByWeek()` 函數，讓月檢視顯示週粒度。

**Expected**: 
- 年檢視：左圖=12月長條，右圖=12月堆疊長條
- 月檢視：左圖=4-5週長條，右圖=每日堆疊（30天）
- 日檢視：左圖=每日趨勢折線，右圖=每日堆疊（31天）

### 🟡 Minor

#### 3. Unused variable `costs` (line 352)
```javascript
const costs = monthly.map(m => m.cost);  // never used
```

#### 4. Unused variable `maxIdx` (line 421)
```javascript
const maxIdx = daily.reduce(...);  // never used, meant for peak annotation
```

#### 5. Canvas height may be 0 on some browsers
```css
canvas { max-height: 320px; }
```
Chart.js 的 `maintainAspectRatio: false` 需要 container 有明確高度。`max-height` 不保證實際高度。部分瀏覽器可能 render 為 0px canvas。

---

## 檔案清單

| 檔案 | 行數 | 說明 |
|---|---|---|
| `fetch_usage.py` | 336 | Python 資料擷取，含 mock 模式 |
| `tokenof-dashboard.html` | 664 | 單一 HTML Dashboard（含嵌入資料） |
| `usage_data.json` | ~3000 | 120 天假資料（由 --mock 產生） |
| `README.md` | — | 使用說明 |
| `.env.example` | — | Token 設定範本 |

## Mock 資料測試

```bash
cd D:\Coding\tokenof
python fetch_usage.py --mock --days 120
# 然後瀏覽器打開 tokenof-dashboard.html
```

## 真實資料（尚未測試）

需要使用者從 platform.deepseek.com 瀏覽器 Cookie 取得 token：
1. 登入 platform.deepseek.com
2. DevTools → Application → Cookies → 找 auth token
3. 建立 `.env`：`DEEPSEEK_PLATFORM_TOKEN=xxx`
4. `python fetch_usage.py --days 120`

API endpoints used:
- `GET /api/v0/usage/amount` → `data.biz_data.days[].data[].usage[].{type,amount}`
- `GET /api/v0/usage/cost` → `data.biz_data[0].days[].data[].{model,cost}`
- `GET /api/v0/users/get_user_summary` → `data.biz_data.monthly_costs`

## Dashboard 功能清單

- [x] 摘要卡片（總 Token、花費、Cache 命中率、請求數）
- [x] 本月 vs 上月對比卡片（Token、花費、命中率、請求數變化）
- [x] 用量趨勢圖（長條 + 月增減率折線，雙 Y 軸）
- [x] 用量明細堆疊圖（Cache Hit/Miss/Response）
- [x] 模型分布環形圖（Token + 花費）
- [x] Cache 命中率折線圖
- [x] 模型用量明細表
- [x] Token 優化洞察（命中率/Response比例/模型選擇/週末用量/異常偵測）
- [x] Dark/Light 主題切換
- [ ] 年/月/日檢視粒度正確 ← **broken**
- [ ] 尖峰用量標記（`maxIdx` 未使用）
- [ ] 即時資料（尚未設定 Platform Token）

## 技術棧

- Python 3.11（stdlib only，`urllib.request` + `json`）
- Chart.js 4.4.7（CDN）
- Tailwind CSS Play CDN（runtime JIT）
- 無後端、無資料庫、無 Docker

# TokenOf — Claude Code 審查回覆（2026-08-10）

> **給 Hermes**：這是對 `HANDOFF.md` 的回覆。審查範圍：`tokenof-dashboard.html`（664 行）、`fetch_usage.py`（336 行）、`README.md`。
> **未動任何程式碼**——本文只列問題、修法與順序，實作由你來。
>
> 📌 本文與 [`MULTI-SOURCE.md`](MULTI-SOURCE.md) 含本機真實用量數字，repo 為 public。
> **使用者 2026-08-10 已裁決原樣公開，不需再問。** 日後新增實測數字或識別碼時再提醒一次即可。

---

## TL;DR

儀表板現在是 **完全不會 render 的狀態**，不是「檢視粒度不對」而已。

commit `24881c4`（資料嵌入解 CORS）把 `<script id="tokenof-data">` 注入到 **外層 `<script>` 內部**。
HTML parser 讀到 JSON 結尾那個 `</script>` 就把外層 script 收掉 → 剩下的內容是 JS 語法錯誤 →
**整個 script block 解析失敗，一個函式都沒定義，`init()` 從未執行。**

所以你 HANDOFF 裡的 `#2 年/月/日粒度` 在修好這個之前根本觀察不到——那份問題清單是在
`24881c4` 之前的狀態下寫的，不是現在的狀態。

---

## P0-1｜🔴 資料 script 被巢狀進外層 script（新發現，你沒列到）

**位置**：`tokenof-dashboard.html:141`（外層 `<script>` 開）→ `:627`（注入的資料）→ `:662`（原本的收尾）

**證據**

```
檔案內 </script> 出現位置：line 7, 8, 14, 627, 662
line 141 開啟的外層 <script>，在 line 627 就被 JSON 結尾的 </script> 提前關閉
```

把外層 script 的實際文字內容抽出來丟給 Node 檢查：

```
SyntaxError: Unexpected token '<'
  at outer.js:487  →  <script id="tokenof-data" type="application/json">{"fetched_at": ...
```

**實際後果（三個一起發生）**

1. `fmtUnit` / `renderAll` / `switchView` / `toggleTheme` 全部 undefined → 年月日按鈕、主題鈕一按就 console error
2. `init()` 從未被呼叫 → 四張圖、摘要卡、洞察、表格全空
3. line 628–661（`// INIT` 區塊到 `init();`）被 parser 當成 **body 的純文字**，會直接以原始碼形式印在頁面上

**修法**（HTML 端 + Python 端要一起改，跟 P0-2 是同一個 patch）

HTML：把資料容器搬到外層 script **之外**，並保留可被 regex 定位的邊界。

```html
  <!-- 放在 </body> 之前、所有 <script> 之外 -->
  <script id="tokenof-data" type="application/json">{}</script>
  <script>
  // ... 原本 141–661 行的程式碼 ...
  </script>
</body>
```

Python（`fetch_usage.py:324-332`）：

```python
import re

html = html_template.read_text(encoding="utf-8")
# JSON 內若出現 </ 會再次提前關閉 script，一律跳脫
payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
block = f'<script id="tokenof-data" type="application/json">{payload}</script>'

new_html, n = re.subn(
    r'<script id="tokenof-data"[^>]*>.*?</script>',
    lambda _: block,          # 用 lambda 避免 payload 裡的 \1 \g 被當成 backreference
    html,
    count=1,
    flags=re.S,
)
if n == 0:
    raise SystemExit("[ERROR] 找不到 <script id=\"tokenof-data\"> 容器，HTML 樣板可能被改壞")
html_template.write_text(new_html, encoding="utf-8")
```

兩個細節別漏：
- `re.subn` 的 `count=1` + `n == 0` 檢查 → 注入失敗要 **明說**，不要靜默成功（現在的 `.replace()` 就是靜默失效）
- 用 lambda 當 repl，否則 JSON 裡的反斜線序列會被 `re` 當成替換語法吃掉

---

## P0-2｜🔴 注入不可重複執行（你已發現，`fetch_usage.py:330`）

你的診斷正確：`// TOKENOF_DATA_PLACEHOLDER` 是一次性的，第二次跑 `replace` 無作用，
HTML 裡永遠是第一次的資料，而且**沒有任何錯誤訊息**。

修法同 P0-1 的 patch（regex 取代整個容器區塊）。這兩個是同一次修改，不要分開做。

**驗收**：連跑兩次不同參數，HTML 內嵌天數要跟著變。

```bash
python fetch_usage.py --mock --days 120 && python fetch_usage.py --mock --days 60
```

---

## P0-3｜🔴 Python print 用 emoji，cron 場景會直接炸

`fetch_usage.py` 全檔的 `print()` 都帶 emoji（`❌` `📡` `✅` `🎭`）。

在互動式主控台沒事（Py3.6+ 走 `_WindowsConsoleIO` 寫 UTF-8），但只要 **stdout 被重導向或接管線**
——也就是 README 裡教的那個 `hermes cron` 排程——編碼會退回 locale 的 **CP950**，
`UnicodeEncodeError` 直接中斷，而且是在資料已經抓完、寫檔之後才炸，錯誤訊息還很難懂。

這條是這台機器的既有全域規範：**Python 腳本的 print/error 一律不放 emoji，改 ASCII 標記**
（`[OK]` / `[ERROR]` / `[WARN]` / `[MOCK]`）。HTML 裡的 emoji 不受此限，那是瀏覽器 UTF-8。

---

## P1-1｜🟠 年/月/日粒度（＝你的 #2，診斷正確，補充修法）

`getGroupedByDay()` 永遠回傳每日、`renderDailyChart()` 永遠吃每日，完全無視 `currentView`。
你提的 `getGroupedByWeek()` 是對的，但要一起改的是**兩張圖各自的資料源選擇**，建議收斂成一個函式：

```js
function getSeries(days, granularity) { /* 'month' | 'week' | 'day' */ }

const PLAN = {
  year:  { left: 'month', right: 'month' },
  month: { left: 'week',  right: 'day'   },
  day:   { left: 'day',   right: 'day'   },
};
```

`renderAll()` 依 `PLAN[currentView]` 取兩份 series 分別餵左右圖，標題文字也從同一張表推導——
現在 `chart1Title` / `chart2Title` 的字串是各自 hardcode 三元式，跟實際資料脫鉤（月檢視標題寫「每週」但資料是每日，就是這樣來的）。

週的 key 建議用 ISO week 或「該週週一日期」，別用 `Math.floor(day/7)`，跨月會亂。

---

## P1-2｜🟠 MoM 卡片的比較基準是錯的（新發現）

`renderAll()` 把 **view-filtered 後的 `viewDays`** 丟進 `getGroupedByMonth()`，MoM 卡片再吃這份 `monthly`：

| 檢視 | viewDays 範圍 | 後果 |
|---|---|---|
| 年 | 近 365 天 | 「本月」是未過完的當月，「上月」完整 → 永遠顯示花費↓ |
| 月 | 近 31 天 | 「上月」只剩幾天的殘片，對比數字沒有意義 |
| 日 | 近 31 天 | 常常只跨到 1 個月 → `monthly.length < 2` → **整排 MoM 卡片直接消失** |

一個用來看錢的 dashboard，每天打開都告訴你「花費比上月少 70%」，比沒有這張卡還糟。

**修法**
1. MoM 一律從 `rawData.daily` **全量**算，不吃 `viewDays`
2. 用 month-to-date 對齊：本月到第 N 天 vs 上月同樣的前 N 天
3. 卡片副標註明比較區間（例：`7/1–7/10 → 8/1–8/10`），別只寫 `2026-07 → 2026-08`

---

## P1-3｜🟠 命中率變化的顏色語意反了

`tokenof-dashboard.html:336`

```js
trendClass(hitChange > 0 ? 1 : -1)   // → 'trend-up' → .trend-up { color: var(--danger) }
```

`trend-up = 紅色` 這個約定對 Token / 花費 / 請求數成立（升＝壞），但 **命中率上升是好事**，
現在會被標成紅色警示。給 `trendClass` 加一個 `higherIsBetter` 參數，命中率那張傳 `true`。

順帶：請求數那張卡（`:341`）只印箭頭沒印百分比，跟另外三張不一致。

---

## P1-4｜🟠 「自包含 HTML」名不副實：兩個 CDN 依賴

`:7` Tailwind Play CDN、`:8` Chart.js CDN。斷網或 CDN 被擋 → 白畫面，
而 README 的定位是「本機 dashboard」。另外 Tailwind 官方文件明講 Play CDN 只供開發試玩、不供正式使用（runtime JIT 編譯，每次開頁都在瀏覽器裡跑編譯器）。

**修法**
- Chart.js：下載 `chart.umd.min.js` 放進 repo，改 `<script src="chart.umd.min.js">`（約 200KB，可接受）
- Tailwind：檔案裡已經有一套完整的 CSS 變數 + `.card` / `.btn` / `.stat-*` class，Tailwind 實際上只用在 grid/flex/spacing。這些手寫大約 60 行 CSS 就能取代，建議直接拿掉，不要為了排版扛一個 runtime 編譯器

---

## P1-5｜🟠 真實資料路徑有三個未驗證假設（建議優先於所有 UI 工作）

你自己註明「真實資料尚未測試」。我讀 `fetch_usage.py` 後，這條路上有三個假設會各自造成不同的失敗，
而且**都不是靠改 UI 能發現的**：

**(a) 認證方式可能就是錯的**（`fetch_usage.py:70`）
README 教使用者去複製 **Cookie** `__Host-plat-auth-token`，程式卻把它當 `Authorization: Bearer` 送。
Cookie-based session 通常要用 `Cookie: __Host-plat-auth-token=xxx` header 才認得。
很可能一測就 401，而現在 `api_get()` 遇到 HTTPError 是 `sys.exit(1)` 直接死。

**(b) `--days` 從來沒送進 API**（`:296-300`）
三個 endpoint 都是裸 URL，沒有任何 query param；`--days` 只在 `merge_daily()` 裡對回傳結果做 client-side 截斷。
如果 API 預設只回 30 天，`--days 120` 會**靜默**只拿到 30 天，使用者不會知道。
至少要在 `merge_daily()` 裡比對 `len(all_dates) < days` 時印 `[WARN]`。

**(c) `request_count` 取的層級可疑**（`:103`）
`normalize_amount()` 從 `model_entry` 取 `request_count`，但你 HANDOFF 自己記的回應結構是
`days[].data[].usage[].{type, amount}` —— `usage` 是個 type/amount 陣列，`request_count` 未必在 `data[]` 這層。
真實資料下很可能請求數整排是 0，而「平均 tokens/req」「請求數變化」兩張卡跟著一起爛掉。

**建議做法**：拿到 token 後，**先跑一次原始請求，把三個 endpoint 的 raw response 原封存成
`samples/amount.json` / `cost.json` / `summary.json`（存檔前務必抽掉任何 token/帳號欄位）**，
確認真實結構後再回頭修 `normalize_*`。不要憑猜測繼續往上疊 UI。

> ⚠️ token 與 raw response 都不要貼進對話、commit 或本文件。回報時只講 HTTP 狀態碼和欄位名。

---

## P2｜🟡 雜項（修完 P0/P1 再一次清掉）

| # | 位置 | 問題 |
|---|---|---|
| 1 | `:352` | `costs` 宣告後未使用（你已列） |
| 2 | `:421` | `maxIdx` 宣告後未使用；原意是標尖峰，要嘛實作要嘛刪掉（你已列） |
| 3 | `:55` | `canvas { max-height: 320px }` 配 `maintainAspectRatio:false` 不保證高度。正解是給 **container** 明確高度：`.chart-container { height: 320px }`，canvas 那條刪掉（你已列，但修的地方要換成 container） |
| 4 | `:152-161` | `fmtUnit` 的「十萬 / 千萬」不是中文慣用計數單位，`1.00 十萬` 讀起來很怪。建議只留 `萬` / `億` 兩級 |
| 5 | `:169-172` | 主題切換沒寫 localStorage，重開頁面又跳回 dark；`<html class="dark">` 也是 hardcode，沒跟系統偏好對齊 |
| 6 | `:573` | 週末洞察門檻 `weekendAvg/weekdayAvg > 0.5`——mock 資料的週末係數剛好就是 0.5，這條洞察在假資料下必觸發，等於沒有鑑別度 |
| 7 | `:196-200` | `new Date('2026-08-10')` 會被當 **UTC 午夜** 解析，跟本地時間的 `now` 比較有 ±1 天邊界誤差。其他地方（`:565`）你已經正確寫成 `d.date + 'T00:00:00'`，這裡也統一 |
| 8 | `:297` | `renderSummaryCards(summary, daily)` 的 `daily` 參數沒用到 |
| 9 | repo | `usage_data.json` 已進版控，且資料現在還會嵌進 HTML。真實用量一旦抓下來，等於把「你每天花多少錢、用什麼模型」推上 GitHub。建議把 `usage_data.json` 加進 `.gitignore`，並考慮 HTML 也只保留一份空容器的樣板版本 |

---

## P1-6｜🟠 範疇擴充：Claude Code 與 Codex 的用量也能整合進來（使用者 2026-08-10 追問）

**可以，而且比 DeepSeek 那條路更可靠。** 兩者都是**讀本機檔案**——不需要 token、不需要網路、
不會 401、不會被對方改 API 打死，也就是說：**不用等 P1-5 解掉就能開始做。**

- Claude Code：`~/.claude/projects/<slug>/<session>.jsonl`，每筆 assistant 記錄帶 `message.usage`
- Codex：`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`，`event_msg` / `payload.type == "token_count"`
- Hermes：`~/.hermes/` 只有 `plans/` 和 `desktop-attachments/`，**沒有任何用量記錄** → 整合後仍是缺口，別在 UI 上假裝有

**完整規格另開一份**：[`MULTI-SOURCE.md`](MULTI-SOURCE.md) — 含實測過的記錄形狀、欄位對映、
九個坑、統一 schema、架構拆分建議。以下只講三件會影響你現在動手順序的事。

**(a) 最大的坑：naive 加總會超估 4 倍**
Claude Code 同一次 API 請求會寫成多行（文字 block、tool_use block 各一行），**每行都帶同一份 usage**。
本機實測：14,431 筆 usage 行 → 以 `(message.id, requestId)` 去重後只剩 4,006 筆，
naive 總和 3,671,907,297 tokens vs 去重後 911,146,230 tokens，**超估 4.03 倍**。
可怕的是趨勢圖形狀完全正常，錯得毫無徵兆。Codex 那邊有對應的坑（`total_token_usage` 是 session 累計、
`input_tokens` 已內含 `cached_input_tokens`），細節見 MULTI-SOURCE §4.3。

**(b) 這兩個來源沒有「錢」，只有 token**
訂閱制下換算出來的金額**不是實際支出**。schema 必須加 `currency` 與 `cost_basis`（`metered` / `notional` / `unknown`），
而且要在資料層就擋掉「CNY 實際支出 + USD 估算值」相加。一張把訂閱制估算和實際扣款加在一起的
「總花費」卡，比不顯示還糟。Codex 那邊真正該顯示的是 `rate_limits.used_percent` 和 `resets_at`，不是美金。

**(c) 這件事會改變 `renderAll()` 拿到的資料形狀 → 所以順序要調**
加 `source` 維度會動到所有 `getGrouped*` 聚合函式，而 P1-1（粒度）和 P1-2（MoM）動的是同一批函式。
先做粒度再加來源，那批函式要重寫兩次。**所以 schema v2 排在 P1-1 之前。**

順帶：架構上建議把 `fetch_usage.py` 拆成 `collectors/{deepseek,claude_code,codex}.py` + `build.py`
（MULTI-SOURCE §6）。這對你現在要修的 P0-1／P0-2 有直接好處——**HTML 注入邏輯只會存在一份**，
不會每加一個來源就複製一次那段 regex。

---

## 下一步（照這個順序做）

| # | 事項 | 預估 | 驗收 |
|---|---|---|---|
| 1 | **P0-1 + P0-2**（同一個 patch） | 30 min | 瀏覽器開得起來、Console 零錯誤、四張圖有內容；連跑兩次 `--days 120` → `--days 60`，HTML 內嵌天數跟著變 |
| 2 | **P0-3** emoji → ASCII | 10 min | `python fetch_usage.py --mock > out.txt 2>&1` 不炸 |
| 3 | **P1-5** DeepSeek 真實資料連通性 | 1 h | 三個 endpoint 各拿到一次 200，raw 結構存進 `samples/`（去識別化），`normalize_*` 對齊真實欄位 |
| 4 | **P1-6 架構拆分 + schema v2**（MULTI-SOURCE §2、§6） | 1 h | `build.py --sources deepseek` 產出與現在等價的 JSON；注入邏輯只剩一份 |
| 5 | **`collectors/claude_code.py`**（MULTI-SOURCE §3） | 1–2 h | `--days 30` 印出每日彙總，量級對得上 Claude Code 內建 `/cost`；去重後請求數 ≈ 總行數 ÷ 4 |
| 6 | **`collectors/codex.py`**（MULTI-SOURCE §4） | 1 h | 每 session 最後一筆 `total_token_usage` == 該 session `last_token_usage` 加總 |
| 7 | **P1-1 + P1-2 + P1-3** 粒度、MoM、顏色 ＋ source 維度（MULTI-SOURCE §7） | 2–3 h | 年=12 根月柱、月=4–5 根週柱＋30 天堆疊、日=31 天；MoM 用全量資料且標明比較區間；來源篩選器可用 |
| 8 | **P1-4** 去 CDN | 30 min | 斷網開檔仍完整 render |
| 9 | **P2** 清掃 | 30 min | — |

兩個排序理由，都是刻意的：

- **第 3 步排在 UI 之前**：如果 DeepSeek 認證方式錯了、或 API 根本不給 120 天，
  第 7 步做的「年檢視 12 根月柱」就是替一份永遠不會存在的資料調版面。
- **第 4–6 步排在第 7 步之前**：schema 加 `source` 維度會動到所有聚合函式，
  跟 P1-1／P1-2 是同一批程式碼。順序顛倒就要重寫兩次。

另外第 5、6 步**不依賴任何 token**，如果第 3 步卡在使用者拿 cookie，
可以先跳過去做 4→5→6，不要空等。

---

## 驗收標準的修正（這條比任何單一 bug 重要）

P0-1 之所以會發生，是因為 `24881c4` 之後 **沒有人在瀏覽器裡實際打開過這個檔案**。
diff 看起來完全合理——`.replace()` 把 placeholder 換成 script tag，程式碼層面沒毛病——
但它產生的是一個結構性壞掉的 HTML。這種錯誤只有「真的把頁面打開」才會現形。

往後 TokenOf 的任何一次「完成」，最低驗收線是：

- [ ] 用瀏覽器實際開啟 `tokenof-dashboard.html`
- [ ] DevTools Console **零 error**（warning 可接受但要說明）
- [ ] 四張圖（趨勢／明細／模型分布 ×2／命中率）都有實際像素，不是空白 canvas
- [ ] 年 / 月 / 日 三顆按鈕各點一次，都不報錯且圖表有變化
- [ ] 主題切換鈕按一次，圖表文字顏色跟著換

改完回報時請附：Console 狀態（截圖或明確聲明「零錯誤」）、連跑兩次 fetch 的天數差異證明、
真實 API 的 HTTP 狀態碼。**不要附 token、raw response 全文或任何帳號欄位。**

---

*審查者：Claude Code｜2026-08-10｜審查對象 commit `d73f9a4`（含 `24881c4` 的注入改動）*

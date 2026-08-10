# TokenOf 多來源整合規格 — Claude Code / Codex

> 撰寫：Claude Code｜2026-08-10｜狀態：**規格，未實作**
> 本文所有欄位結構與坑都是在本機實測過的（`C:\Users\User\.claude\projects\`、`C:\Users\User\.codex\sessions\`），不是憑印象寫的。
>
> 📌 **本文含本機真實用量數字與識別碼**（§1 規模、§3.3 G1 的 token 總量、§3.1 的 `requestId`／`sessionId`、§4.1 的 `plan_type`／`resets_at`）。
> 自用無妨，**但這個 repo 的 remote 是 public**——要 push 前先問使用者是否要去識別化（換佔位符 + 相對比例，技術結論不受影響）。
> 相關：[`HANDOFF-CC-2026-08-10.md`](HANDOFF-CC-2026-08-10.md)（審查與待辦順序）

---

## 結論先講

**可以，而且這條路比 DeepSeek 那條更可靠。**

DeepSeek 要靠使用者手動從瀏覽器複製 session cookie、打未公開的內部 API（`HANDOFF-CC-2026-08-10.md` P1-5 列的三個未驗證假設都還沒解）。
Claude Code 和 Codex 則是**直接讀本機檔案**——不需要 token、不需要網路、不會 401、不會被改 API 打死。

代價是：**這兩個來源的檔案裡沒有「錢」**，只有 token。要不要換算成金額、以及換算出來的數字算不算「花費」，是這次整合最關鍵的設計決定（見 §5）。

---

## 1. 能力矩陣（本機實測）

| 來源 | 資料位置 | 有 token | 有金額 | 有請求數 | 有模型別 | 有額度/餘額 |
|---|---|---|---|---|---|---|
| **DeepSeek** | 遠端 API（需 cookie） | ✅ | ✅ 實際計費 CNY | ✅ | ✅ | 未接 |
| **Claude Code** | `~/.claude/projects/*/*.jsonl` | ✅ | ❌ 需自備定價表 | ✅ 可推導 | ✅ | ❌ |
| **Codex** | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` | ✅ | ❌ | △ 只有輪次 | ✅ | ✅ **有額度 %** |
| **Hermes** | `~/.hermes/` 只有 `plans/`、`desktop-attachments/` | ❌ | ❌ | ❌ | ❌ | ❌ |

本機實測規模（供評估工程量，**若 repo 要公開請把這段數字刪掉**）：

- Claude Code：31 個 jsonl、14,431 筆帶 usage 的記錄、47 天有資料（2026-05-14 起）、6 種模型
- Codex：7 個 session、35 筆 `token_count` 事件（這台機器用得少）
- Hermes：**沒有任何本機用量記錄可解析** → 這是整合後仍然存在的缺口，別在 dashboard 上假裝有

---

## 2. 統一 schema（v2）

現在的 `usage_data.json` 是「單一來源 × 日 × 模型」。加來源等於多一個維度，`daily[]` 的形狀要改：

```jsonc
{
  "fetched_at": "2026-08-10T04:30:24Z",
  "sources": ["deepseek", "claude-code", "codex"],   // 這次抓到哪些
  "daily": [
    {
      "date": "2026-08-10",
      "source": "claude-code",          // deepseek | claude-code | codex
      "models": {
        "claude-opus-5": {
          "prompt_cache_hit": 0,        // 讀到快取的 input
          "prompt_cache_miss": 0,       // 沒讀到快取的 input（含建立快取的部分）
          "response": 0,                // output
          "request_count": 0,
          "cost": 0.0,
          "currency": "USD",            // CNY | USD
          "cost_basis": "notional"      // metered | notional | unknown
        }
      },
      "total_tokens": 0,
      "cache_hit_rate": 0.0,
      "request_count": 0
    }
  ]
}
```

**三個新欄位是這次整合的重點，不是裝飾**：

- `source` — 讓 dashboard 能篩選、能分色，也讓「總計」這件事變成一個明確的選擇而非預設
- `currency` — DeepSeek 是 CNY、另外兩家是 USD。**不同幣別絕對不可以直接相加**
- `cost_basis` —
  - `metered`：真的按量扣錢（DeepSeek API）
  - `notional`：訂閱制下用公開定價換算出來的「如果走 API 會花多少」，**不是實際支出**
  - `unknown`：沒有定價表可換算

> ⚠️ 一個把 `metered` 和 `notional` 加在一起的「總花費」數字，比不顯示還糟——它會讓人以為自己這個月花了幾百美金，實際上訂閱費是固定的。這件事必須在 schema 層擋掉，不能只靠 UI 加註解。

`prompt_cache_miss` 的定義要跨來源統一成「**沒有從快取讀到的 input token**」，各來源的欄位對映見下兩節。

---

## 3. Claude Code collector 規格

### 3.1 資料位置與記錄形狀

```
C:\Users\User\.claude\projects\<專案路徑 slug>\<session-uuid>.jsonl
```

一行一筆 JSON。要的是 `message.usage` 存在的那些行：

```jsonc
{
  "type": "assistant",
  "timestamp": "2026-06-22T08:21:03.109Z",
  "requestId": "req_011CcHyP4QJ5xVarBvyqWYZN",
  "sessionId": "5226b534-...",
  "isSidechain": false,
  "cwd": "...", "gitBranch": "master", "version": "2.1.181",
  "message": {
    "id": "msg_...",
    "model": "claude-sonnet-4-6",
    "usage": {
      "input_tokens": 0,
      "cache_creation_input_tokens": 0,
      "cache_read_input_tokens": 0,
      "output_tokens": 0,
      "cache_creation": { "ephemeral_1h_input_tokens": 6671, "ephemeral_5m_input_tokens": 0 },
      "server_tool_use": { "web_search_requests": 0, "web_fetch_requests": 0 },
      "service_tier": "standard",
      "iterations": [ { "input_tokens": 1, "output_tokens": 404, "cache_read_input_tokens": 158826, "cache_creation_input_tokens": 6671 } ]
    }
  }
}
```

### 3.2 欄位對映

| TokenOf 欄位 | Claude Code 來源 |
|---|---|
| `date` | `timestamp[:10]`（UTC；要換本地時區就明確做，別靠 `new Date()` 隱式轉） |
| `model` | `message.model` |
| `prompt_cache_hit` | `usage.cache_read_input_tokens` |
| `prompt_cache_miss` | `usage.input_tokens + usage.cache_creation_input_tokens` |
| `response` | `usage.output_tokens` |
| `request_count` | 去重後的記錄數（見 G1） |
| `cost` | 無——需自備定價表，且 `cost_basis: "notional"` |

### 3.3 五個坑（每一個都實測過）

**G1｜一次 API 請求會寫成多行，naive 加總會超估 4 倍**

同一個 `requestId` 底下會有多行 assistant 記錄（文字 block、tool_use block 各一行），
而**每一行都帶著同一份 usage**。實測本機資料：

```
usage 行數 = 14,431   去重後 (message.id, requestId) = 4,006
naive 總和 = 3,671,907,297 tokens
去重總和 =   911,146,230 tokens
超估倍數 = 4.03x
```

→ **必須以 `(message.id, requestId)` 為鍵去重**。這是整個 collector 最重要的一行邏輯，寫錯的話所有數字都是假的，而且假得很有說服力（趨勢圖形狀完全正常）。

**G2｜少數記錄 top-level usage 全為 0，真值在 `iterations[]`**

實測 14,431 筆中有 33 筆四個 token 欄位全 0，但 `usage.iterations[]` 裡有數字。
規則：先取 top-level，四欄全 0 時才回頭加總 `iterations[]`。
（全檔比對：top-level 合計與 iterations 合計差 0.04%，所以 top-level 是可信的主要來源，不要反過來只用 iterations。）

**G3｜`<synthetic>` 要排除**

`message.model === "<synthetic>"` 是本地合成的訊息（例如中斷提示），token 全 0，不是 API 呼叫。實測 23 筆。留著會讓「請求數」虛胖。

**G4｜cache_creation 有兩種價，別當成同一種**

`cache_creation.ephemeral_5m_input_tokens` 和 `ephemeral_1h_input_tokens` 單價不同（1 小時的較貴）。
若之後要算 `notional` 成本，這兩個要分開乘。另外 `server_tool_use.web_search_requests` 是**按次**另計費，不在 token 裡。

**G5｜`isSidechain: true` 是 subagent 的訊息**

那是真實花費，**要算進總量**。但它同時是個好用的維度——可以拆出「指揮官自己用掉多少 vs 派出去的 subagent 用掉多少」。以這個 wiki 的模型調度制度（`canon/10_model-dispatch.md` 講「指揮官不下場」）來說，這個拆分其實比模型分布更有洞察力，值得當成 v2 的一張圖。

**G6｜增量掃描**

jsonl 是 append-only，且 session 會被續寫。每次全量重掃 31 個檔（含 9MB 的大檔）尚可接受，
但要排程每小時跑就該記 `(檔名, 已讀 offset, mtime)` 做增量。先做全量，慢了再優化。

---

## 4. Codex collector 規格

### 4.1 資料位置與記錄形狀

```
C:\Users\User\.codex\sessions\2026\07\23\rollout-2026-07-23T16-11-13-<uuid>.jsonl
```

記錄格式是 `{timestamp, type, payload}`。實測出現的類型：
`session_meta` / `turn_context` / `world_state` / `response_item/*` / `event_msg/*`。

要的是 `event_msg` 且 `payload.type === "token_count"`：

```jsonc
{
  "timestamp": "2026-07-23T08:12:40.185Z",
  "type": "event_msg",
  "payload": {
    "type": "token_count",
    "info": {
      "total_token_usage": {          // ← session 累計
        "input_tokens": 13947,
        "cached_input_tokens": 11008,
        "cache_write_input_tokens": 0,
        "output_tokens": 141,
        "reasoning_output_tokens": 51,
        "total_tokens": 14088
      },
      "last_token_usage": { /* 同結構，但只有這一輪 */ },
      "model_context_window": 258400
    },
    "rate_limits": {
      "plan_type": "plus",
      "primary": { "used_percent": 0.0, "window_minutes": 10080, "resets_at": 1785399153 },
      "credits": { "has_credits": false, "unlimited": false, "balance": "0" }
    }
  }
}
```

### 4.2 欄位對映

| TokenOf 欄位 | Codex 來源 |
|---|---|
| `date` | `timestamp[:10]` |
| `model` | `turn_context.payload.model`（實測值：`gpt-5.6-terra`）；**不在 `session_meta` 裡** |
| `prompt_cache_hit` | `cached_input_tokens` |
| `prompt_cache_miss` | `input_tokens − cached_input_tokens`（見 G2） |
| `response` | `output_tokens`（`reasoning_output_tokens` 是它的子集，別另外加） |
| `request_count` | `token_count` 事件數（≈ 輪次，不是 API 請求數，語意要註明） |
| `cost` | 無 → `cost_basis: "unknown"` 或自備定價表算 `notional` |

### 4.3 四個坑

**G1｜`total_token_usage` 是 session 累計，不是單輪**

把所有 `token_count` 事件的 `total_token_usage` 相加會嚴重重複計算。
兩個正確做法（實測兩者結果完全一致）：
- 取每個 session **最後一筆** `total_token_usage`，或
- 加總所有 `last_token_usage`

實測 7 個 session 的每 session（最後總計, last 加總）完全相等，總計 2,196,501 tokens。

**G2｜`input_tokens` 已經包含 `cached_input_tokens`**

驗證：`total_tokens (14088) = input_tokens (13947) + output_tokens (141)`，
而 `cached_input_tokens (11008) < input_tokens`。
→ miss = `input − cached`。**寫成 `input + cached` 會憑空多出一倍 input。**

**G3｜模型可能中途換**

`model` 在 `turn_context`，而 `turn_context` 一個 session 可能出現多次（實測 7 個 session 共 14 筆）。
要按時間軸把 `token_count` 對應到「最近一筆 `turn_context` 的 model」，不能整個 session 套同一個模型。

**G4｜`rate_limits` 才是訂閱制使用者真正想看的**

`used_percent` / `window_minutes` / `resets_at` / `plan_type` / `credits.balance` ——
對一個 Plus 訂閱使用者來說，「這週額度用了 63%、週四 14:00 重置」遠比「換算成 12.4 美金」有用。
**建議 Codex 這塊的主視覺不要做成金額卡，做成額度環圈 + 重置倒數。**

---

## 5. 計價：不要把訂閱制和計量制加在一起

| 來源 | 計費模式 | 本文件的立場 |
|---|---|---|
| DeepSeek API | 按量扣款 | `cost_basis: "metered"`，是真的錢 |
| Claude Code（訂閱） | 月費固定 | `cost_basis: "notional"`，換算值只能當「使用強度」指標 |
| Codex（Plus） | 月費固定 + 額度上限 | 同上；真正的稀缺資源是**額度 %**不是錢 |

具體規則：

1. 摘要卡的「總花費」在多來源模式下**拆成兩張**：「實際支出（CNY）」與「等值估算（USD, 訂閱制）」，中間不做加總
2. `notional` 的數字在 UI 上要有視覺區隔（灰字／虛線框），hover 說明「訂閱制，非實際支出」
3. 定價表放獨立的 `pricing.json`，標明 `source` 與 `updated_at`，**不要 hardcode 進 Python 或 HTML**。單價會變，而且我不打算憑記憶寫死任何一個數字——這張表請從各家官方定價頁抄，抄的時候記下日期
4. 沒有定價表時就填 `cost: null` + `cost_basis: "unknown"`，UI 顯示 `—`。**不要猜。**

---

## 6. 架構：不要讓 `fetch_usage.py` 繼續長大

現在 `fetch_usage.py` 一支負責「抓 DeepSeek + normalize + 寫 JSON + 注入 HTML」。再塞兩個來源進去會變成一坨。

```
tokenof/
├── collectors/
│   ├── deepseek.py      # 遠端 API（需 token）
│   ├── claude_code.py   # 讀 ~/.claude/projects/*/*.jsonl
│   └── codex.py         # 讀 ~/.codex/sessions/**/rollout-*.jsonl
├── pricing.json         # 各模型單價 + updated_at（手動維護）
├── build.py             # 呼叫 collectors → 合併 → 寫 usage_data.json → 注入 HTML
└── tokenof-dashboard.html
```

每個 collector 只做一件事：**回傳一個符合 §2 schema 的 `list[dict]`**，不寫檔、不碰 HTML。

```bash
python build.py --sources claude-code,codex        # 不需要任何 token，離線可跑
python build.py --sources all --days 120
```

好處有三個，其中兩個是立即的：
- **HTML 注入邏輯只會存在一份**（`HANDOFF-CC-2026-08-10.md` 的 P0-1／P0-2 只需要修在 `build.py` 一個地方）
- Claude Code / Codex 兩個 collector **不需要 token 就能開發和測試**，不必卡在 DeepSeek 認證未解（P1-5）
- 之後要加 Gemini / Hermes 只是多一個檔案

---

## 7. Dashboard 端要改什麼

1. **來源篩選器**：Header 加一排 `全部 / DeepSeek / Claude Code / Codex`，跟現有的年月日切換並列
2. **`getDaysInView()` 之後多一層 source 過濾**，且所有 `getGrouped*` 都要能按 `(date, source)` 聚合
3. **模型分布環圈按 source 分組**——把 `deepseek-v4-pro` 和 `claude-opus-5` 混在同一個環圈裡沒有意義
4. **摘要卡拆幣別**（見 §5）
5. **Codex 專屬的額度卡**：`used_percent` 環圈 + `resets_at` 倒數
6. **新增一張「Sidechain 佔比」圖**（Claude Code 專屬，見 §3.3 G5）——subagent 用掉多少，這對模型調度制度是直接可行動的資訊
7. **缺資料要老實顯示**：某來源當天沒資料，畫成空缺不要補 0；Hermes 沒有資料來源就完全不要出現在 UI 上

---

## 8. 這件事該排在什麼時候做

**建議插在 P1-5 之後、P1-1（檢視粒度）之前。**

理由：schema 從「單一來源」變成「多來源」會改變 `renderAll()` 拿到的資料形狀，
而 P1-1 的粒度重構、P1-2 的 MoM 修正都是在動同一批聚合函式。
先做粒度再加 source 維度＝那批函式要重寫兩次。

修正後的順序：

| # | 事項 | 預估 |
|---|---|---|
| 1 | P0-1 + P0-2（script 巢狀 + 重複注入） | 30 min |
| 2 | P0-3（emoji → ASCII） | 10 min |
| 3 | P1-5（DeepSeek 真實資料連通性） | 1 h |
| 4 | **§6 架構拆分 + §2 schema v2** | 1 h |
| 5 | **`collectors/claude_code.py`**（含 G1 去重，本文件五個坑都有實測依據） | 1–2 h |
| 6 | **`collectors/codex.py`** | 1 h |
| 7 | P1-1 + P1-2 + P1-3（粒度、MoM、顏色）＋ §7 的 source 維度 | 2–3 h |
| 8 | P1-4（去 CDN）、P2 雜項 | 1 h |

第 5 步可以先獨立驗收：`python collectors/claude_code.py --days 30` 直接印出每日彙總，
跟 Claude Code 內建的 `/cost` 對一下同一天的數字量級。對不上就是 G1～G3 哪個沒處理。

---

## 9. 我沒有驗證、動手前要自己查的事

誠實列出來，別把這幾條當成已知：

- **Anthropic Admin API 的 usage/cost report**：組織層級的用量報表端點需要 admin key，這台機器上沒有，我無從驗證。而且**訂閱制的 Claude Code 用量不一定會出現在 API 帳單裡**——如果目標是「看訂閱用了多少」，本機 jsonl 仍然是唯一的事實來源
- **Claude Code 的 OTel/metrics 匯出**：可能有更乾淨的官方管道，值得先查一次再決定要不要自己解 jsonl
- **`ccusage` 之類現成工具**：社群已有讀同一批 jsonl 的工具，可以考慮直接吃它的輸出而不自己寫 collector。但它跟 Claude Code 版本的相容性要驗（本機是 `2.1.181`，`usage.iterations` 這個結構未必每版都有）
- **各家定價**：一律從官方定價頁抄，抄的時候把日期寫進 `pricing.json`
- **時區**：兩邊的 timestamp 都是 UTC。使用者在台灣，UTC+8 會讓「今天」的邊界差 8 小時。要在 collector 統一轉成本地日期，並在文件寫明用的是哪個時區——現在 DeepSeek 那邊的日期是 API 給的（推測是北京時間），三個來源不對齊會讓跨來源比較失真

---

*規格撰寫：Claude Code｜2026-08-10｜實測環境：Windows 10 / Claude Code 2.1.181 / Codex CLI 0.145.0*

# Tokenof — Token 用量儀表板

簡單清晰的 Token 用量 Dashboard，取代各家官方難讀的圖表。目前實作 DeepSeek，
多來源（Claude Code / Codex）規格見 [`MULTI-SOURCE.md`](MULTI-SOURCE.md)。

> ⚠️ **目前狀態：dashboard 無法運作**（資料 script 被巢狀進外層 script，整段 JS 解析失敗）。
> 問題清單與修復順序見 [`HANDOFF-CC-2026-08-10.md`](HANDOFF-CC-2026-08-10.md)。

## 功能

- 📊 年/月/日 三種檢視模式
- 💰 本月 vs 上月花費對比
- 📈 Token 用量趨勢（Cache Hit/Miss/Response）
- 🎯 Cache 命中率追蹤
- 🤖 模型用量分布
- 💡 Token 優化洞察建議

## 快速開始

### 1. 取得 Platform Token

1. 瀏覽器開啟 https://platform.deepseek.com 並登入
2. 按 F12 打開 DevTools
3. 進入 **Application** → **Cookies** → `platform.deepseek.com`
4. 尋找名為 `__Host-plat-auth-token`（或類似名稱）的 Cookie
5. 複製其 Value

### 2. 設定環境變數

在專案目錄建立 `.env` 檔：

```
DEEPSEEK_PLATFORM_TOKEN=你的_token_貼這裡
```

或設定系統環境變數：

```powershell
setx DEEPSEEK_PLATFORM_TOKEN "你的_token"
```

### 3. 擷取資料

```bash
cd C:/Users/User/tokenof
python fetch_usage.py
```

### 4. 打開 Dashboard

```bash
start tokenof-dashboard.html
```

或直接用瀏覽器打開 `tokenof-dashboard.html`。

## 定時自動更新（選用）

用 Hermes cron job 每小時自動更新：

```bash
hermes cron create "0 * * * *" --prompt "cd C:/Users/User/tokenof && python fetch_usage.py" --name "tokenof-hourly-fetch"
```

## 檔案說明

| 檔案 | 用途 |
|---|---|
| `fetch_usage.py` | 從 DeepSeek Platform API 擷取用量資料 |
| `usage_data.json` | 快取的用量資料（自動產生） |
| `tokenof-dashboard.html` | 自包含 HTML Dashboard |
| `.env` | Platform Token（不進版本控制） |
| `HANDOFF-CC-2026-08-10.md` | Claude Code 審查回覆：問題清單與修復順序 |
| `MULTI-SOURCE.md` | Claude Code / Codex 用量整合規格（未實作） |

## 授權

MIT

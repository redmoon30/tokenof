# Tokenof — Token 用量儀表板

多來源 Token 用量儀表板（DeepSeek / Claude Code / Codex），取代各家官方難讀的用量圖表。

## 功能

- 📊 年/月/日 三種檢視粒度
- 💰 本月 vs 上月花費對比（MTD 對齊）
- 🎯 Cache 命中率追蹤
- 🤖 多來源模型分布（來源分色）
- 💡 Token 優化洞察建議
- 🔋 Codex 訂閱額度卡

## 架構

```
tokenof/
├── build.py                    # 主入口：呼叫 collectors → 合併 → 寫 JSON → 注入 HTML
├── collectors/
│   ├── deepseek.py             # 遠端 API（需 token）
│   ├── claude_code.py          # 讀 ~/.claude/projects/*/*.jsonl（離線）
│   └── codex.py                # 讀 ~/.codex/sessions/**/rollout-*.jsonl（離線）
├── tokenof-dashboard.html      # 自包含 HTML Dashboard（資料由 build.py 注入）
└── usage_data.json             # 輸出（已 gitignore，含真實用量不上傳）
```

## 快速開始

### 離線來源（不需 token）

```bash
python build.py --sources claude-code,codex --days 90
```

### DeepSeek（需 Platform Token）

1. 瀏覽器登入 https://platform.deepseek.com
2. `F12` → Application → Cookies → `platform.deepseek.com`
3. 複製 auth token cookie 的 value
4. 建立 `.env`：
   ```
   DEEPSEEK_PLATFORM_TOKEN=xxx
   ```
5. ```bash
   python build.py --sources deepseek --days 90
   ```

### 全部來源

```bash
python build.py --sources all --days 90
```

### 測試（DeepSeek 假資料）

```bash
python build.py --sources all --mock
```

執行後用瀏覽器打開 `tokenof-dashboard.html`。

## 定時更新（選用）

```bash
hermes cron create "0 * * * *" --prompt "cd D:/Coding/tokenof && python build.py --sources all" --name "tokenof-hourly"
```

## 檔案說明

| 檔案 | 用途 |
|---|---|
| `build.py` | 主入口，合併來源 + 注入 HTML |
| `collectors/deepseek.py` | DeepSeek 平台 API（需 token） |
| `collectors/claude_code.py` | Claude Code 本機 jsonl |
| `collectors/codex.py` | Codex 本機 jsonl |
| `tokenof-dashboard.html` | 自包含 HTML Dashboard |
| `.env` | DeepSeek token（不進版本控制） |

## 審查文件

- `HANDOFF-CC-2026-08-10.md` — Claude Code 審查回覆（P0/P1/P2 問題清單）
- `MULTI-SOURCE.md` — 多來源整合規格（schema v2、欄位對映、坑）

## 授權

MIT

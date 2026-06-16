---
name: python-utf8-source-reads
description: 當在此專案中需要讀取任何原始碼、設定檔、Markdown、含中文 UI 文案或中文欄位名稱的檔案內容時使用。此技能強制禁止使用 PowerShell 文字讀檔方式（例如 Get-Content、type、cat 的 PowerShell 別名）讀取檔案內容；一律使用 Python 並明確指定 UTF-8 編碼來讀取。可用 rg 搜尋檔名或關鍵字，但實際展開檔案內容時必須改用 Python UTF-8 讀取。
---

# Python UTF-8 讀碼規範

此專案含有 Traditional Chinese UI 文案、欄位名稱與說明文字。
在 Windows / PowerShell 環境下，直接用 PowerShell 讀文字內容容易把 UTF-8 檔案顯示成亂碼，進而誤判實際程式內容。

## 不可違反的規則

1. 不得使用 PowerShell 文字讀檔命令讀取檔案內容。
2. 禁止的讀法包含 `Get-Content`、`type`、`cat` 的 PowerShell 別名，以及任何會透過 PowerShell 預設編碼解讀文字的方式。
3. 需要查看檔案內容時，一律使用 Python，並明確指定 `encoding="utf-8"`。
4. 可以用 `rg` 搜尋檔名、函式名、關鍵字與行號。
5. `rg` 找到目標後，若要看實際內容，必須改用 Python UTF-8 讀取。

## 標準做法

先搜尋：

```powershell
rg -n "關鍵字" path/to/file.py
```

再讀內容：

```powershell
python -c "from pathlib import Path; print(Path(r'path/to/file.py').read_text(encoding='utf-8'))"
```

若只想看部分內容，也要用 Python 處理切片，不要改回 PowerShell 讀檔：

```powershell
python -c "from pathlib import Path; lines=Path(r'path/to/file.py').read_text(encoding='utf-8').splitlines(); start=120; end=170; print('\n'.join(f'{i+1}:{line}' for i, line in enumerate(lines[start-1:end], start-1)))"
```

## 適用範圍

- `pages/*.py`
- `render_layer/*.py`
- `data_layer/*.py`
- `Inventory.py`
- `AGENTS.md`
- `.md` 規格文件
- 任何含中文註解、中文字串、中文欄位名的檔案

## 目的

1. 避免把顯示亂碼誤認成檔案已損壞。
2. 避免因讀取錯誤而重打或誤改中文字串。
3. 讓後續 patch 與驗證建立在真實 UTF-8 內容上。

## 補充

- 這個技能只約束「讀取檔案內容」的方式。
- 修改原始碼仍優先使用 `apply_patch`。
- 不要因為只是快速查看，就回到 PowerShell 讀檔。

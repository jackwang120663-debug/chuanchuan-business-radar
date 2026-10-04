# 串串商機雷達

自動搜尋公開網頁上的近期商機線索，整理成 CSV 與 Excel 報表。

## 目前設定

- 平台：Threads、Facebook、Instagram、YouTube、TikTok 的公開搜尋結果
- 關鍵字：在 `config.json` 修改
- 時間範圍：60 分鐘內；無法確認發布時間的結果不收錄
- 排程：每 6 小時執行一次（台灣時間約 02:17、08:17、14:17、20:17）
- 不登入社群帳號、不留言、不自動聯絡任何人

## 手動執行

1. 打開本資料庫上方的 **Actions**
2. 點左邊的 **串串商機雷達**
3. 點 **Run workflow**
4. 完成後打開該次執行紀錄，在 **Artifacts** 下載 `chuanchuan-radar-...`
5. ZIP 內含 `latest.csv`、`latest.xlsx` 與 `summary.json`

## 修改關鍵字

編輯 `config.json` 的 `keywords` 清單即可。設定 `strict_recent_only` 為 `false` 可保留發布時間無法確認的搜尋結果。

> 搜尋引擎與社群網站可能更改頁面或限制收錄，因此結果不保證完整。程式只處理公開搜尋結果。

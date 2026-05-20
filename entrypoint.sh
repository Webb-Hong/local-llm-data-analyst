#!/bin/sh
# 容器啟動時先執行:確保資料就緒,再啟動 API
# 這讓容器「自給自足」,不依賴外部先手動建資料

echo "[entrypoint] 產生資料庫..."
python -m src.make_data

echo "[entrypoint] 啟動 API..."
exec uvicorn src.api:app --host 0.0.0.0 --port 8000
# Dockerfile：描述「怎麼把這個專案打包成一個 image」的食譜
# 每一行是一個步驟，Docker 照著一步步建出 image

# 步驟1：從一個「已經裝好 Python 的基礎 image」開始
#   不用自己從零裝 Python，站在現成的基礎上（這就是 image 分層的概念）
FROM python:3.13-slim

# 步驟2：設定容器內的「工作目錄」
#   之後的指令都在這個目錄下執行（呼應你學過的工作目錄概念）
WORKDIR /app

# 步驟3：先只複製 requirements.txt 進去，然後裝套件
#   為什麼先複製這個就好？這是 Docker 分層快取的優化（下面解釋，面試考點）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 步驟4：把專案程式碼複製進容器
COPY src/ ./src/
COPY knowledge/ ./knowledge/

# 步驟5：宣告這個容器會用到的 port（FastAPI 跑在 8000）
EXPOSE 8000

# 步驟6：容器啟動時要執行的指令
#   注意：用 0.0.0.0 而不是 localhost，這是容器網路的關鍵（任務3會深入）
# 複製啟動腳本並賦予執行權限
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# 容器啟動時執行腳本(先建資料,再起 API)
CMD ["./entrypoint.sh"]
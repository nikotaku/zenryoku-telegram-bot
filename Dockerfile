FROM python:3.11-slim

# 日本語フォントと必要なシステムパッケージをインストール
RUN apt-get update && apt-get install -y \
    fontconfig \
    fonts-noto-cjk \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]

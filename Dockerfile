FROM python:3.9-alpine

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ENV TOKEN=discord_bot_token <-- discord bot token here

COPY database.py main.py ./

CMD ["python", "main.py"]
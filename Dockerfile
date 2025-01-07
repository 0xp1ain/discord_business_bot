FROM python:3.9-alpine

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ENV TOKEN=your_token_here

COPY database.py main.py ./
VOLUME /app/db

CMD ["python", "main.py"]
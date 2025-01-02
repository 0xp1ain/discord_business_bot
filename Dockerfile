FROM python:3.9-alpine
WORKDIR /app
COPY database.py /app
COPY main.py /app


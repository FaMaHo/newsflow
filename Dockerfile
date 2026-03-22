FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py database.py ai_engine.py config.py ./
RUN mkdir -p /app/data
CMD ["python", "-u", "bot.py"]

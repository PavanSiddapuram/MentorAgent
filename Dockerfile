FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./

# Railway injects env vars at runtime — no .env file needed
# credentials.json and token.json are decoded from env vars by start.py
CMD ["python", "start.py"]

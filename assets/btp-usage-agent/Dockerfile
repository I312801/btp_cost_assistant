FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir "fastapi>=0.111.0" "uvicorn[standard]>=0.29.0"

# Copy application source directly into WORKDIR so uvicorn can find server:app
COPY app/ .

# Environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Health probe and A2A server port
EXPOSE 5001

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "5001"]
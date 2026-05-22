FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install dependencies (fastapi, uvicorn[standard] and all others are in requirements.txt)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source directly into WORKDIR so uvicorn can find server:app
COPY app/ .

# Environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LLM_BACKEND=joule \
    JOULE_MODEL=gpt-4o

# Health probe and A2A server port
EXPOSE 5001

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "5001"]
# Morsegrid AI Revenue Recovery Agent — Cloud Run image.
# Needs BOTH Python (agents/dashboard) and Node.js (the MongoDB MCP server).
FROM python:3.12-slim

# Node.js 20 for the MongoDB MCP server (`npx mongodb-mcp-server`).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Pre-install the MCP server so it does NOT download on a cold start.
RUN npm install -g mongodb-mcp-server@latest

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV GOOGLE_GENAI_USE_VERTEXAI=TRUE \
    PYTHONUNBUFFERED=1 \
    PORT=8080

EXPOSE 8080

# Cloud Run sets $PORT (8080). Streamlit must bind 0.0.0.0.
CMD ["sh", "-c", "streamlit run dashboard.py --server.port=${PORT} --server.address=0.0.0.0"]

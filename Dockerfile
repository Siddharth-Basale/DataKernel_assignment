FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py agent1_graph.py agent2_graph.py agent3_graph.py agent4_graph.py agent5_graph.py ./
COPY dataset.csv .

# Render sets PORT (often 10000)
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
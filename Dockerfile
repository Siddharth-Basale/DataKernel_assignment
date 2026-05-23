FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py agent1_graph.py agent2_graph.py agent3_graph.py ./
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

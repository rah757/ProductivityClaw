FROM python:3.12-slim

WORKDIR /app

# Copy dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY agent/ agent/
COPY data/ data/

# Set the python path so module imports work
ENV PYTHONPATH=/app

CMD ["python", "agent/main.py"]

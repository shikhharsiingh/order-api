# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the current directory contents into the container at /engine
COPY . /app

CMD ["uvicorn", "engine:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
# CMD ["python", "watcher.py"]

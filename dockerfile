# Use Python 3.9 slim image as the base
FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install gunicorn

# Copy the rest of the application
COPY . .

# Expose the port the app runs on
EXPOSE 8080

# Set the PATH to include the local bin directory where gunicorn is installed
ENV PATH="/usr/local/bin:${PATH}"

# Make the start script executable
RUN chmod +x start.sh

RUN pwd

RUN ls -la

# Command to run the application
CMD ["./start.sh"]


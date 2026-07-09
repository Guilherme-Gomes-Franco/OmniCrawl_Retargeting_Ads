FROM mcr.microsoft.com/playwright/python:v1.60.0-jammy 

# Set the working directory
WORKDIR /app

# Install required system tools (Xvfb for virtual display, libnss3-tools for certutil)
RUN apt-get update && apt-get install -y \
    xvfb \
    libnss3-tools \
    curl \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Brave Browser Native Binary
RUN curl -fsSLo /usr/share/keyrings/brave-browser-archive-keyring.gpg https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/brave-browser-archive-keyring.gpg] https://brave-browser-apt-release.s3.brave.com/ stable main" | tee /etc/apt/sources.list.d/brave-browser-release.list \
    && apt-get update && apt-get install -y brave-browser \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir mitmproxy beautifulsoup4 playwright attrs setuptools cryptography

# Copy your entire project into the container
COPY . /app/

# Make the entrypoint script executable
RUN chmod +x /app/entrypoint.sh

# Set the entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]
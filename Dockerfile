FROM mcr.microsoft.com/playwright/python:v1.61.0-jammy 

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    xvfb \
    libnss3-tools \
    curl \
    gnupg \
    dbus-x11 \
    && rm -rf /var/lib/apt/lists/*

# Install Brave
RUN curl -fsSLo /usr/share/keyrings/brave-browser-archive-keyring.gpg https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/brave-browser-archive-keyring.gpg] https://brave-browser-apt-release.s3.brave.com/ stable main" | tee /etc/apt/sources.list.d/brave-browser-release.list \
    && apt-get update && apt-get install -y brave-browser \
    && rm -rf /var/lib/apt/lists/*

# CRITICAL: Pin Playwright to 1.61.0 here
RUN pip install --no-cache-dir \
    mitmproxy \
    beautifulsoup4 \
    playwright==1.61.0 \
    attrs \
    setuptools \
    cryptography

COPY . /app/
RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
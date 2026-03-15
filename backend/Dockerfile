FROM python:3.11-slim

# Install TeX Live (xelatex) and supporting packages
RUN apt-get update && apt-get install -y --no-install-recommends \
        texlive-xetex \
        texlive-fonts-recommended \
        texlive-latex-recommended \
        texlive-plain-generic \
        fonts-liberation \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies (requirements.txt is in the build context = backend/)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source into backend/ so that `from backend.X` imports resolve
# (Render sets rootDir: backend, so the build context root is backend/)
COPY . backend/

EXPOSE 8000

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

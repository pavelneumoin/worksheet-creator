# Use Python with TeX Live pre-installed
FROM python:3.11-slim

# Install TeX Live and required packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    texlive-latex-base \
    texlive-fonts-recommended \
    texlive-latex-extra \
    texlive-lang-cyrillic \
    texlive-xetex \
    cm-super \
    lmodern \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && which pdflatex && pdflatex --version

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 10000

# Set environment variables
ENV USE_CLOUD_LATEX=false
ENV PYTHONUNBUFFERED=1

# Run the application
CMD ["gunicorn", "--chdir", "backend", "app:app", "--bind", "0.0.0.0:10000"]

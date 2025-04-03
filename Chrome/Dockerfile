FROM python:3.9-slim

# Imposta la directory di lavoro
WORKDIR /Chrome

# Copia il file requirements.txt
COPY requirements.txt .

# Installa le dipendenze
RUN pip install --no-cache-dir -r requirements.txt

# Copia lo script Python
COPY script.py .

# Comando di default per eseguire lo script
CMD ["python", "script.py"]
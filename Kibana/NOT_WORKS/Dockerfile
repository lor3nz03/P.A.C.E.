FROM docker.elastic.co/kibana/kibana:8.17.0

USER 0
ADD kibana.yml /usr/share/kibana/config
# Crea la cartella per la dashboard
RUN mkdir -p /usr/share/kibana/dashboard

# Copia il file NDJSON della dashboard e lo script di importazione nel container
COPY dashboard.ndjson /usr/share/kibana/dashboard/dashboard.ndjson
COPY import_dashboard.sh /usr/local/bin/import_dashboard.sh

# Rendi eseguibile lo script
RUN chmod +x /usr/local/bin/import_dashboard.sh

# Imposta lo script di importazione come entrypoint
ENTRYPOINT ["/usr/local/bin/import_dashboard.sh"]

USER kibana
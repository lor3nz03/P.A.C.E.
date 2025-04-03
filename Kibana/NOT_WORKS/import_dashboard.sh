#!/bin/bash
set -e

echo "Avvio Kibana..."
/usr/share/kibana/bin/kibana &
kibana_pid=$!

echo "Attesa che Kibana diventi disponibile..."
until curl -s http://localhost:5601/api/status | grep -q '"state":"green"'; do
  echo "Kibana non è ancora pronto..."
  sleep 5
done

echo "Kibana è 'green'. Attesa extra per la stabilizzazione..."
sleep 10

echo "Importo la dashboard..."
response=$(curl -s -w "\nHTTP_CODE:%{http_code}" -X POST "http://localhost:5601/api/saved_objects/_import?overwrite=true" \
  -H "kbn-xsrf: true" \
  --form file=@/usr/share/kibana/dashboard/dashboard.ndjson)

echo "Risposta dalla richiesta curl:"
echo "$response"

if echo "$response" | grep -q "HTTP_CODE:200"; then
  echo "Importazione completata con successo."
else
  echo "Attenzione: la richiesta di importazione ha restituito un errore."
fi

echo "Container in esecuzione..."
tail -f /dev/null

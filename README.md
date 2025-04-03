# P.A.C.E. - Predictive Age & Category Engine

## Introduzione

P.A.C.E. è un sistema avanzato di analisi predittiva progettato per monitorare e analizzare il comportamento di navigazione degli utenti in tempo reale. Il progetto utilizza tecnologie moderne come Spark, Kafka, Elasticsearch e Docker per raccogliere, elaborare e analizzare i dati di navigazione, con l'obiettivo di prevedere la fascia d'età degli utenti in base alle categorie di pagine visitate.

## Funzionalità principali

- **Monitoraggio in tempo reale**: Traccia i siti visitati dagli utenti e il tempo trascorso su ciascuno.
- **Classificazione delle categorie**: Associa ogni sito a una categoria predefinita (es. educazione, intrattenimento, social media, ecc.).
- **Predizione della fascia d'età**: Utilizza un modello di machine learning per prevedere la fascia d'età dell'utente basandosi sui dati di navigazione.
- **Integrazione con Elasticsearch**: Archivia i dati aggregati e le predizioni per analisi e visualizzazioni future.
- **Scalabilità e portabilità**: Grazie a Docker, il sistema è facilmente scalabile e portabile su qualsiasi ambiente.

---

## Architettura del progetto

Il progetto è composto da diversi servizi, ciascuno con un ruolo specifico. Di seguito una panoramica dei servizi e delle porte utilizzate:

### 1. **Python App (Chrome Monitoring)**
- **Descrizione**: Monitora i siti visitati dagli utenti tramite il browser Chrome e invia i dati a Fluentd.
- **Tecnologia**: Python con libreria `pychrome`.
- **Porte**: 
  - `9222`: Porta per il controllo remoto di Chrome.
- **Motivazione**: Permette di catturare in tempo reale i dati di navigazione degli utenti.

### 2. **Fluentd**
- **Descrizione**: Aggrega i dati di navigazione ricevuti dalla Python App e li invia a Kafka.
- **Tecnologia**: Fluentd.
- **Porte**:
  - `24224`: Porta per ricevere i dati dalla Python App.
- **Motivazione**: Garantisce un'integrazione fluida tra i dati raccolti e il sistema di messaggistica Kafka.

### 3. **Kafka (Broker)**
- **Descrizione**: Sistema di messaggistica distribuito utilizzato per trasmettere i dati di navigazione tra i servizi.
- **Tecnologia**: Apache Kafka.
- **Porte**:
  - `9999`: Porta per la comunicazione con i produttori e consumatori di messaggi.
- **Motivazione**: Garantisce un sistema affidabile e scalabile per la gestione dei dati in tempo reale.

### 4. **Spark**
- **Descrizione**: Elabora i dati di navigazione ricevuti da Kafka, applica il modello di machine learning e invia i risultati a Elasticsearch.
- **Tecnologia**: Apache Spark.
- **Porte**:
  - `8080`: Interfaccia web di Spark.
  - `7077`: Porta per il cluster manager di Spark.
- **Motivazione**: Spark è ideale per l'elaborazione di grandi volumi di dati in tempo reale.

### 5. **Elasticsearch**
- **Descrizione**: Archivia i dati aggregati e le predizioni per analisi e visualizzazioni.
- **Tecnologia**: Elasticsearch.
- **Porte**:
  - `9200`: Porta per l'accesso all'API REST di Elasticsearch.
  - `9300`: Porta per la comunicazione interna del cluster.
- **Motivazione**: Fornisce un sistema di archiviazione scalabile e performante per i dati.

### 6. **Kibana**
- **Descrizione**: Interfaccia grafica per visualizzare i dati archiviati in Elasticsearch.
- **Tecnologia**: Kibana.
- **Porte**:
  - `5601`: Porta per accedere all'interfaccia web di Kibana.
- **Motivazione**: Permette di creare dashboard e visualizzazioni per analizzare i dati raccolti.

---

## Perché Docker?

Abbiamo scelto Docker per i seguenti motivi:
- **Isolamento**: Ogni servizio è eseguito in un container separato, evitando conflitti tra dipendenze.
- **Portabilità**: L'intero sistema può essere eseguito su qualsiasi macchina con Docker installato.
- **Scalabilità**: È possibile scalare facilmente i servizi in base alle esigenze.
- **Facilità di configurazione**: Grazie a Docker Compose, tutti i servizi possono essere avviati con un singolo comando.

---

## Come utilizzare il progetto

### Prerequisiti
- Docker  installati sulla macchina.

### Avvio del sistema
1. Clona il repository del progetto:
   ```bash
   git clone <repository-url>
   cd <repository-folder>
   ```
2. Avvia i servizi con Docker Compose:
   ```bash
   docker-compose up --build
   ```
3. Accedi ai servizi:
   - **Kibana**: [http://localhost:5601](http://localhost:5601)
   - **Spark Web UI**: [http://localhost:8080](http://localhost:8080)
   - **Elasticsearch API**: [http://localhost:9200](http://localhost:9200)

### Monitoraggio in tempo reale
- Assicurati che il browser Chrome sia avviato con il controllo remoto abilitato:
  ```bash
  google-chrome --remote-debugging-port=9222
  ```
- La Python App inizierà a monitorare i siti visitati e invierà i dati al sistema.

### Visualizzazione dei dati
- Utilizza Kibana per creare dashboard e visualizzare i dati raccolti e le predizioni.

---

## Conclusioni

P.A.C.E. è un sistema completo e scalabile per l'analisi predittiva del comportamento di navigazione. Grazie all'integrazione di tecnologie moderne e all'uso di Docker, il progetto è facilmente configurabile e adattabile a diversi scenari. Per qualsiasi domanda o contributo, potete contattarmi all'email lorenzodibella15@gmail.com!
from pyspark.sql import SparkSession
from pyspark.sql.functions import from_json, col, udf, lit, expr, current_timestamp, date_format, hour
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, FloatType, DoubleType, ArrayType
from pyspark.ml.pipeline import PipelineModel
import os
import json
import time
from collections import defaultdict
from datetime import datetime

# ---------------------------
# Impostazioni Kafka e definizione dello schema JSON per i dati in ingresso
# ---------------------------
schema = StructType([
    StructField("site", StringType(), True),       
    StructField("seconds", IntegerType(), True),     
    StructField("timestamp", FloatType(), True),    
    StructField("status", StringType(), True)        
])

# ---------------------------
# Definizione delle categorie e mappatura dei siti
# ---------------------------
CATEGORIES = ['educazione', 'intrattenimento', 'social media', 'notizie',
              'shopping', 'tecnologia', 'professionale', 'gaming', 'sport', 'finanza', 'unknown']

json_path = "/opt/spark/apps/lista.json"
if os.path.exists(json_path):
    print("File trovato!")
else:
    print("File NON trovato!")

with open(json_path, "r") as f:
    site_categories = json.load(f)

print("JSON caricato correttamente!")

def match_label(site):
    """
    Estrae il dominio base ed effettua la mappatura del sito alla categoria
    basata sul file JSON di configurazione.
    """
    base_domain = site.split('.')[-2] if '.' in site else site
    return site_categories.get(base_domain, site_categories.get(site, "unknown"))

match_label_udf = udf(match_label, StringType())

# ---------------------------
# Inizializzazione della SparkSession
# ---------------------------
spark = SparkSession.builder.appName("SessionTrackingAgePrediction").getOrCreate()
spark.sparkContext.setLogLevel("ERROR")

# ---------------------------
# Caricamento del modello di Machine Learning (caricato una sola volta all'avvio)
# ---------------------------
model_path = "/opt/spark/apps/model-spark"
model = PipelineModel.load(model_path)
print("Modello ML caricato correttamente all'avvio!")

# ---------------------------
# Strutture dati per memorizzare le sessioni e le statistiche aggregate
# ---------------------------
active_sessions = {}      
session_history = []      
cumulative_site_time = defaultdict(int)  

# Contatori per le fasce orarie
time_of_day_counters = {
    "mattina": 0,
    "pomeriggio": 0,
    "sera": 0,
    "notte": 0
}
# Set per tracciare i siti già conteggiati per ciascuna fascia oraria
counted_sites = {
    "mattina": set(),
    "pomeriggio": set(),
    "sera": set(),
    "notte": set()
}

# ---------------------------
# Schema per il documento combinato destinato a Elasticsearch
# ---------------------------
combined_schema = StructType([
    StructField("timestamp", DoubleType(), True),            
    StructField("process_datetime", StringType(), True),       
    StructField("predicted_age_group", StringType(), True),      
    StructField("navigation_records", ArrayType(               
        StructType([
            StructField("site", StringType(), True),
            StructField("category", StringType(), True),
            StructField("seconds", IntegerType(), True),
            StructField("timestamp", DoubleType(), True),
            StructField("part_of_day", StringType(), True),
            StructField("status", StringType(), True),
            StructField("process_time", DoubleType(), True)
        ])
    ), True)
])

# ---------------------------
# Variabili globali per la gestione della variabile d'appoggio per la predizione
# ---------------------------
last_ml_update_time = 0     # Tempo dell'ultimo reset della variabile d'appoggio
ml_navigation_data = []     # Variabile d'appoggio: qui vengono registrati i dati di navigazione

# ---------------------------
# Funzioni di aggiornamento delle sessioni e di predizione
# ---------------------------
def update_session_data(site, seconds, timestamp, status):
    """
    Aggiorna la struttura dati delle sessioni.
      - Se il sito è già attivo e riceve aggiornamenti "active", si aggiorna il tempo.
      - Se lo status è "closed", la sessione viene terminata e il tempo si aggiunge a quello cumulativo.
    """
    global active_sessions, session_history, cumulative_site_time
    if site in active_sessions and status == "active":
        active_sessions[site] = {"seconds": seconds, "timestamp": timestamp, "status": status}
        print(f"Aggiornata sessione attiva per {site}: {seconds} secondi")
    elif site in active_sessions and status == "closed":
        cumulative_site_time[site] += seconds
        print(f"Aggiornato tempo cumulativo per {site}: ora totale {cumulative_site_time[site]} secondi")
        session_history.append({"site": site, "seconds": seconds, "timestamp": timestamp, "status": "closed"})
        del active_sessions[site]
        print(f"Chiusa sessione per {site} e aggiunta alla cronologia: {seconds} secondi")
    elif site not in active_sessions and status == "active":
        active_sessions[site] = {"seconds": seconds, "timestamp": timestamp, "status": status}
        print(f"Nuova sessione attiva per {site}: {seconds} secondi")
    elif site not in active_sessions and status == "closed":
        cumulative_site_time[site] += seconds
        print(f"Aggiornato tempo cumulativo per {site}: ora totale {cumulative_site_time[site]} secondi")
        session_history.append({"site": site, "seconds": seconds, "timestamp": timestamp, "status": "closed"})
        print(f"Aggiunta sessione già chiusa per {site}: {seconds} secondi")

def get_recent_navigation_data(time_window_seconds=60):
    """
    Restituisce i record di navigazione (sia dalle sessioni attive che chiuse)
    aventi un timestamp entro l'intervallo degli ultimi 'time_window_seconds'.
    """
    current_time = time.time()
    time_threshold = current_time - time_window_seconds
    recent_history = [session for session in session_history if session["timestamp"] >= time_threshold]
    recent_active = []
    for site, info in active_sessions.items():
        if info["timestamp"] >= time_threshold:
            recent_active.append({
                "site": site,
                "seconds": info["seconds"],
                "timestamp": info["timestamp"],
                "status": info["status"]
            })
    recent_data = recent_history + recent_active
    #print(f"Dati recenti: {len(recent_data)} sessioni negli ultimi {time_window_seconds} secondi")
    return recent_data

def predict_age_group(navigation_data):
    """
    Calcola le percentuali di tempo speso per ciascuna categoria dai dati forniti e
    utilizza il modello ML per predire la fascia d'età.
    """
    if not navigation_data:
        print("Nessun dato di navigazione disponibile per la predizione")
        return None

    categorized_data = []
    for record in navigation_data:
        site = record["site"]
        category = match_label(site)
        seconds = record["seconds"]
        categorized_data.append({"site": site, "category": category, "seconds": seconds})

    category_seconds = defaultdict(int)
    for item in categorized_data:
        category_seconds[item["category"]] += item["seconds"]

    total_seconds = sum(category_seconds.values())
    if total_seconds == 0:
        print("Totale secondi è zero, impossibile calcolare percentuali")
        return None

    percentages = {}
    for category in CATEGORIES:
        seconds = category_seconds.get(category, 0)
        percentages[f"{category}_pct"] = seconds / total_seconds

    # Assicura che ogni categoria abbia una percentuale (anche se zero)
    for category in CATEGORIES:
        if f"{category}_pct" not in percentages:
            percentages[f"{category}_pct"] = 0.0

    model_input = percentages.copy()
    model_input["age_group"] = "unknown"
    model_input_df = spark.createDataFrame([model_input])
    
    prediction = model.transform(model_input_df)
    predicted_age = prediction.select("predicted_age_group").collect()[0][0]
    print("\n--- DISTRIBUZIONE PERCENTUALI PER CATEGORIA (finestra 2 minuti) ---")
    for category in CATEGORIES:
        pct = percentages[f"{category}_pct"] * 100
        print(f"{category}: {pct:.1f}%")
    print("Contenuto della variabile d'appoggio:")
    for record in ml_navigation_data:
        print(record)
    return predicted_age

def update_time_of_day_counter(site, part_of_day, status):
    """
    Aggiorna il contatore della fascia oraria:
      - Incrementa il contatore se il sito è in sessione attiva e non già contato.
      - Rimuove il sito dal set se la sessione viene chiusa.
    """
    global time_of_day_counters, counted_sites
    if status == "active" and site not in counted_sites[part_of_day]:
        time_of_day_counters[part_of_day] += 1
        counted_sites[part_of_day].add(site)
        #print(f"Incrementato contatore {part_of_day} per sito {site}")
    elif status == "closed" and site in counted_sites[part_of_day]:
        counted_sites[part_of_day].remove(site)
        #print(f"Rimosso sito {site} dal set dei conteggiati per {part_of_day}")

# ---------------------------
# Lettura dei dati dallo stream di Kafka
# ---------------------------
df = spark.readStream.format("kafka") \
    .option("kafka.bootstrap.servers", "broker:9999") \
    .option("subscribe", "browsing_data") \
    .option("startingOffsets", "earliest") \
    .load()

df = df.selectExpr("CAST(value AS STRING)")
parsed_df = df.select(from_json(col("value"), schema).alias("data")).select("data.*")

# ---------------------------
# Funzione per processare ogni batch di dati ricevuti dallo stream
# ---------------------------
def process_batch(batch_df, batch_id):
    global last_ml_update_time, ml_navigation_data

    if batch_df.isEmpty():
        return

    navigation_records = []  # Lista dei record di navigazione processati in questo batch

    for row in batch_df.collect():
        site = row["site"]
        # Filtro: esclude i record dai siti "www.google.it" e "www.google.com"
        if site == "www.google.it" or site == "www.google.com":
            print(f"Scartato sito {site} per filtro")
            continue

        seconds = row["seconds"]
        timestamp = row["timestamp"]
        status = row["status"]

        # Corregge il timestamp aggiungendo 2 ore (7200 secondi)
        corrected_timestamp = timestamp + 7200

        # Determina la fascia oraria basata sull'ora del giorno del timestamp corretto
        hour_val = int(time.strftime("%H", time.localtime(corrected_timestamp)))
        if 5 <= hour_val < 12:
            part_of_day = "mattina"
        elif 12 <= hour_val < 17:
            part_of_day = "pomeriggio"
        elif 17 <= hour_val < 21:
            part_of_day = "sera"
        else:
            part_of_day = "notte"

        update_time_of_day_counter(site, part_of_day, status)
        formatted_kafka_ts = time.strftime("%H:%M:%S - %d-%m-%Y", time.localtime(corrected_timestamp))
        #print(f"Timestamp Kafka per {site}: {formatted_kafka_ts}")

        update_session_data(site, seconds, corrected_timestamp, status)

        navigation_records.append({
            "site": site,
            "category": match_label(site),
            "seconds": seconds,
            "timestamp": corrected_timestamp,
            "part_of_day": part_of_day,
            "status": status,
            "process_time": time.time()
        })

    if not navigation_records:
        print("Nessun sito valido nel batch; salto l'elaborazione.")
        return

    # Gestione della variabile d'appoggio:
    # Se sono trascorsi almeno 2 minuti dall'ultimo reset, si cancella il contenuto
    # e si sostituisce con i dati del batch corrente, altrimenti si accumulano.
    current_time = time.time()
    if current_time - last_ml_update_time >= 120:
        ml_navigation_data = navigation_records[:]  # Sovrascrive con i nuovi dati
        last_ml_update_time = current_time
        print("Variabile d'appoggio resettata e aggiornata con i dati del batch corrente (nuova finestra 2 minuti)")
    else:
        ml_navigation_data.extend(navigation_records)
        print("Variabile d'appoggio aggiornata: nuovi record aggiunti alla finestra corrente")

    # Esegue la predizione usando la variabile d'appoggio (contenente i dati degli ultimi 2 minuti)
    predicted_age = predict_age_group(ml_navigation_data)
    if predicted_age:
        print(f"\n╔══════════════════════════════════════════════╗")
        print(f"║ FASCIA D'ETÀ PREVISTA: {predicted_age.ljust(22)} ║")
        print(f"╚══════════════════════════════════════════════╝\n")
    else:
        print("Impossibile predire la fascia d'età con i dati attuali")

    # Costruisce il documento combinato da inviare a Elasticsearch
    combined_document = {
        "timestamp": time.time(),
        "process_datetime": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time())),
        "predicted_age_group": predicted_age,
        "navigation_records": navigation_records
    }

    combined_df = spark.createDataFrame([combined_document], schema=combined_schema)
    combined_df.write \
        .format("org.elasticsearch.spark.sql") \
        .option("es.nodes", "elasticsearch") \
        .option("es.port", "9200") \
        .option("es.resource", "combined_navigation") \
        .option("es.mapping.id", "timestamp") \
        .mode("append") \
        .save()

    # ---------------------------
    # Invio dei dati per il grafico a barre in Kibana
    # ---------------------------
    simple_documents = [
        {"timestamp": time.time(), "fascia_oraria": "1-mattina", "siti_aperti": time_of_day_counters["mattina"]},
        {"timestamp": time.time(), "fascia_oraria": "2-pomeriggio", "siti_aperti": time_of_day_counters["pomeriggio"]},
        {"timestamp": time.time(), "fascia_oraria": "3-sera", "siti_aperti": time_of_day_counters["sera"]},
        {"timestamp": time.time(), "fascia_oraria": "4-notte", "siti_aperti": time_of_day_counters["notte"]}
    ]
    simple_df = spark.createDataFrame(simple_documents)
    simple_df.write \
        .format("org.elasticsearch.spark.sql") \
        .option("es.nodes", "elasticsearch") \
        .option("es.port", "9200") \
        .option("es.resource", "barchart_fasce_orarie") \
        .option("es.write.operation", "index") \
        .mode("append") \
        .save()
    
    print("Dati inviati a Elasticsearch con struttura semplificata per grafico a barre.")
    
    # ---------------------------
    # Invio della cronologia cumulativa per ciascun sito a Elasticsearch
    # ---------------------------
    cumulative_site_documents = []
    for site, total_seconds in cumulative_site_time.items():
        category = match_label(site)
        cumulative_site_documents.append({
            "timestamp": time.time(),
            "site": site,
            "category": category,
            "seconds_total": total_seconds,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time()))
        })
    
    if cumulative_site_documents:
        cumulative_df = spark.createDataFrame(cumulative_site_documents)
        cumulative_df.write \
            .format("org.elasticsearch.spark.sql") \
            .option("es.nodes", "elasticsearch") \
            .option("es.port", "9200") \
            .option("es.resource", "site_cumulative_time") \
            .option("es.mapping.id", "site") \
            .option("es.write.operation", "upsert") \
            .mode("append") \
            .save()
        print(f"Inviati {len(cumulative_site_documents)} documenti di cronologia cumulativa a Elasticsearch.")
        print("")
        print("")
        print("")

# ---------------------------
# Avvio dello streaming: per ogni micro-batch viene chiamata la funzione process_batch
# ---------------------------
query = parsed_df.writeStream \
    .foreachBatch(process_batch) \
    .outputMode("update") \
    .option("checkpointLocation", "/tmp/spark_checkpoint") \
    .start()

query.awaitTermination()

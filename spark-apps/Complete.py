from pyspark.sql import SparkSession
from pyspark.sql.functions import from_json, col, udf, lit, expr, current_timestamp, date_format, hour
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, FloatType
from pyspark.ml.pipeline import PipelineModel
import os
import json
import time
from collections import defaultdict
from datetime import datetime

# ---------------------------
# Impostazioni Kafka e schema JSON
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

# UDF per mappare il sito alla categoria
def match_label(site):
    base_domain = site.split('.')[-2] if '.' in site else site
    return site_categories.get(base_domain, site_categories.get(site, "unknown"))

match_label_udf = udf(match_label, StringType())

# ---------------------------
# Inizializza SparkSession
# ---------------------------
spark = SparkSession.builder.appName("SessionTrackingAgePrediction").getOrCreate()
spark.sparkContext.setLogLevel("ERROR")

# ---------------------------
# Carica il modello ML una sola volta all'inizio
# ---------------------------
model_path = "/opt/spark/apps/model-spark"
model = PipelineModel.load(model_path)
print("Modello ML caricato correttamente all'avvio!")

# ---------------------------
# Struttura dati per memorizzare le sessioni attive
# ---------------------------
active_sessions = {}   # Chiave: site, Valore: {seconds, timestamp, status}
session_history = []   # Lista delle sessioni completate

# Dizionario per tenere traccia del tempo cumulativo per ogni sito
cumulative_site_time = defaultdict(int)  # Chiave: site, Valore: seconds_total

# Contatori per le fasce orarie
time_of_day_counters = {
    "mattina": 0,
    "pomeriggio": 0,
    "sera": 0,
    "notte": 0
}

# Set per tenere traccia dei siti già conteggiati per ciascuna fascia oraria
# Struttura: {'mattina': set('sito1', 'sito2'), 'pomeriggio': set('sito3'), ...}
counted_sites = {
    "mattina": set(),
    "pomeriggio": set(),
    "sera": set(),
    "notte": set()
}

# Funzione per aggiornare le sessioni
def update_session_data(site, seconds, timestamp, status):
    global active_sessions, session_history, cumulative_site_time
    if site in active_sessions and status == "active":
        active_sessions[site] = {"seconds": seconds, "timestamp": timestamp, "status": status}
        print(f"Aggiornata sessione attiva per {site}: {seconds} secondi")
    elif site in active_sessions and status == "closed":
        # Aggiorna il tempo cumulativo per il sito quando una sessione viene chiusa
        cumulative_site_time[site] += seconds
        print(f"Aggiornato tempo cumulativo per {site}: ora totale {cumulative_site_time[site]} secondi")
        
        session_history.append({"site": site, "seconds": seconds, "timestamp": timestamp, "status": "closed"})
        del active_sessions[site]
        print(f"Chiusa sessione per {site} e aggiunta alla cronologia: {seconds} secondi")
    elif site not in active_sessions and status == "active":
        active_sessions[site] = {"seconds": seconds, "timestamp": timestamp, "status": status}
        print(f"Nuova sessione attiva per {site}: {seconds} secondi")
    elif site not in active_sessions and status == "closed":
        # Aggiorna il tempo cumulativo anche per sessioni già chiuse
        cumulative_site_time[site] += seconds
        print(f"Aggiornato tempo cumulativo per {site}: ora totale {cumulative_site_time[site]} secondi")
        
        session_history.append({"site": site, "seconds": seconds, "timestamp": timestamp, "status": "closed"})
        print(f"Aggiunta sessione già chiusa per {site}: {seconds} secondi")

# Funzione per ottenere i dati di navigazione degli ultimi 60 secondi
def get_recent_navigation_data(time_window_seconds=60):
    current_time = time.time()
    time_threshold = current_time - time_window_seconds
    # Filtra le sessioni chiuse
    recent_history = [session for session in session_history if session["timestamp"] >= time_threshold]
    # Filtra anche le sessioni attive in base al timestamp
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
    print(f"Dati recenti: {len(recent_data)} sessioni negli ultimi {time_window_seconds} secondi")
    return recent_data

# Funzione per predire la fascia d'età (usa il modello globale)
def predict_age_group(navigation_data):
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
        percentages[f"{category}_pct"] = seconds / total_seconds if total_seconds > 0 else 0.0
    for category in CATEGORIES:
        if f"{category}_pct" not in percentages:
            percentages[f"{category}_pct"] = 0.0
    model_input = percentages.copy()
    model_input["age_group"] = "unknown"
    model_input_df = spark.createDataFrame([model_input])
    
    # Usa il modello globale caricato all'inizio
    prediction = model.transform(model_input_df)
    predicted_age = prediction.select("predicted_age_group").collect()[0][0]
    print("\n--- DISTRIBUZIONE PERCENTUALI PER CATEGORIA (ultimo minuto) ---")
    for category in CATEGORIES:
        pct = percentages[f"{category}_pct"] * 100
        if pct > 5:
            print(f"{category}: {pct:.1f}%")
    return predicted_age

# Funzione per gestire il conteggio dei siti per fascia oraria
def update_time_of_day_counter(site, part_of_day, status):
    global time_of_day_counters, counted_sites
    
    # Se il sito è attivo e non è già stato conteggiato per questa fascia oraria
    if status == "active" and site not in counted_sites[part_of_day]:
        time_of_day_counters[part_of_day] += 1
        counted_sites[part_of_day].add(site)
        print(f"Incrementato contatore {part_of_day} per sito {site}")
    
    # Se il sito è chiuso e era stato conteggiato per questa fascia oraria
    elif status == "closed" and site in counted_sites[part_of_day]:
        # Non decrementiamo il contatore, ma rimuoviamo il sito dal set dei conteggiati
        counted_sites[part_of_day].remove(site)
        print(f"Rimosso sito {site} dal set dei conteggiati per {part_of_day}")

# ---------------------------
# Lettura dati da Kafka
# ---------------------------
df = spark.readStream.format("kafka") \
    .option("kafka.bootstrap.servers", "broker:9999") \
    .option("subscribe", "browsing_data") \
    .option("startingOffsets", "earliest") \
    .load()

df = df.selectExpr("CAST(value AS STRING)")
parsed_df = df.select(from_json(col("value"), schema).alias("data")).select("data.*")

# Funzione per processare ogni batch di dati
def process_batch(batch_df, batch_id):
    if batch_df.isEmpty():
        return

    navigation_records = []  # Lista per i record di navigazione

    for row in batch_df.collect():
        site = row["site"]
        seconds = row["seconds"]
        timestamp = row["timestamp"]
        status = row["status"]

        # Correggi il timestamp aggiungendo 2 ore (7200 secondi)
        corrected_timestamp = timestamp + 7200

        # Calcola la fascia oraria in base all'ora del giorno
        hour_val = int(time.strftime("%H", time.localtime(corrected_timestamp)))
        if 5 <= hour_val < 12:
            part_of_day = "mattina"
        elif 12 <= hour_val < 17:
            part_of_day = "pomeriggio"
        elif 17 <= hour_val < 21:
            part_of_day = "sera"
        else:
            part_of_day = "notte"

        # Aggiorna il contatore della fascia oraria
        update_time_of_day_counter(site, part_of_day, status)

        # Stampa il timestamp corretto in formato leggibile
        formatted_kafka_ts = time.strftime("%H:%M:%S - %d-%m-%Y", time.localtime(corrected_timestamp))
        print(f"Timestamp Kafka per {site}: {formatted_kafka_ts}")

        # Aggiorna la struttura dati delle sessioni usando il timestamp corretto
        update_session_data(site, seconds, corrected_timestamp, status)

        # Prepara il record di navigazione per il documento combinato
        navigation_records.append({
            "site": site,
            "category": match_label(site),
            "seconds": seconds,
            "timestamp": corrected_timestamp,
            "part_of_day": part_of_day,
            "status": status,
            "process_time": time.time()
        })

    # Ottieni i dati di navigazione recenti (ultimi 60 secondi)
    recent_navigation = get_recent_navigation_data(time_window_seconds=60)
    print("\n--- STATO ATTUALE DELLA NAVIGAZIONE (ultimo minuto) ---")
    print(f"Sessioni attive: {len(active_sessions)}")
    print(f"Sessioni storiche totali: {len(session_history)}")
    print(f"Dati recenti (ultimi 60 secondi): {len(recent_navigation)}\n")
    
    # Stampa lo stato attuale dei contatori
    print("\n--- CONTATORI FASCE ORARIE ---")
    for time_of_day, count in time_of_day_counters.items():
        print(f"{time_of_day}: {count} siti conteggiati")
    print(f"Dettaglio siti conteggiati: {counted_sites}\n")

    # Stampa lo stato attuale del tempo cumulativo per sito
    print("\n--- TEMPO CUMULATIVO PER SITO ---")
    for site, total_seconds in sorted(cumulative_site_time.items(), key=lambda x: x[1], reverse=True):
        print(f"{site}: {total_seconds} secondi totali")
    print()

    # Effettua la predizione usando solo i dati recenti
    predicted_age = None
    if recent_navigation:
        predicted_age = predict_age_group(recent_navigation)
        if predicted_age:
            print(f"\n╔══════════════════════════════════════════════╗")
            print(f"║ FASCIA D'ETÀ PREVISTA: {predicted_age.ljust(22)} ║")
            print(f"╚══════════════════════════════════════════════╝\n")
        else:
            print("Impossibile predire la fascia d'età con i dati attuali")
    else:
        print("Dati di navigazione insufficienti negli ultimi 60 secondi per fare una predizione")

    # Costruisci il documento aggregato da inviare a Elasticsearch
    combined_document = {
        "timestamp": time.time(),  # Timestamp del momento del processo
        "process_datetime": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time())),
        "predicted_age_group": predicted_age,
        "navigation_records": navigation_records  # Lista dei record di navigazione con le informazioni richieste
    }

    # Crea un DataFrame con il documento combinato
    combined_df = spark.createDataFrame([combined_document])
    
    # Invia il documento di navigazione a Elasticsearch (indice "combined_navigation")
    combined_df.write \
        .format("org.elasticsearch.spark.sql") \
        .option("es.nodes", "elasticsearch") \
        .option("es.port", "9200") \
        .option("es.resource", "combined_navigation") \
        .option("es.mapping.id", "timestamp") \
        .mode("append") \
        .save()
    
    # ----- SOLUZIONE SEMPLIFICATA PER GRAFICO A BARRE IN KIBANA -----
    # Usiamo un approccio diverso: creare un documento separato per ogni fascia oraria
    # con un campo che indica la fascia oraria e uno che contiene il conteggio
    
    # Crea una lista di documenti semplici, uno per ogni fascia oraria
    simple_documents = []
    
    # Crea un documento per ogni fascia oraria con un ID univoco
    simple_documents.append({
        "timestamp": time.time(),
        "fascia_oraria": "1-mattina",  # Prefissiamo con numeri per garantire l'ordine corretto
        "siti_aperti": time_of_day_counters["mattina"]
    })
    
    simple_documents.append({
        "timestamp": time.time(),
        "fascia_oraria": "2-pomeriggio",
        "siti_aperti": time_of_day_counters["pomeriggio"]
    })
    
    simple_documents.append({
        "timestamp": time.time(),
        "fascia_oraria": "3-sera",
        "siti_aperti": time_of_day_counters["sera"]
    })
    
    simple_documents.append({
        "timestamp": time.time(),
        "fascia_oraria": "4-notte",
        "siti_aperti": time_of_day_counters["notte"]
    })
    
    # ID univoco per questo batch, usato come parte del document_id
    batch_id_str = str(int(time.time()))
    
    # Crea un DataFrame con i documenti
    simple_df = spark.createDataFrame(simple_documents)
    
    # Invia i documenti a un nuovo indice dedicato al grafico a barre
    simple_df.write \
        .format("org.elasticsearch.spark.sql") \
        .option("es.nodes", "elasticsearch") \
        .option("es.port", "9200") \
        .option("es.resource", "barchart_fasce_orarie") \
        .option("es.write.operation", "index") \
        .mode("append") \
        .save()
    
    print("Dati inviati a Elasticsearch con struttura semplificata per grafico a barre.")
    
    # ----- NUOVO INDICE PER LA CRONOLOGIA CUMULATIVA DEI SITI -----
    # Creiamo un documento per ogni sito con tempo cumulativo
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
        # Crea un DataFrame con i documenti di cronologia cumulativa
        cumulative_df = spark.createDataFrame(cumulative_site_documents)
        
        # Invia i documenti al nuovo indice per la cronologia cumulativa
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

# Avvia lo streaming e processa ogni micro-batch
query = parsed_df.writeStream \
    .foreachBatch(process_batch) \
    .outputMode("update") \
    .option("checkpointLocation", "/tmp/spark_checkpoint") \
    .start()

query.awaitTermination()
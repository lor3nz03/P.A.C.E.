import numpy as np
import pandas as pd
import random
from pyspark.sql import SparkSession
from pyspark.ml import Pipeline
from pyspark.ml.feature import VectorAssembler, StringIndexer, IndexToString
from pyspark.ml.classification import RandomForestClassifier
from pyspark.ml.evaluation import MulticlassClassificationEvaluator

# Definizione delle categorie e distribuzioni per fascia d'età
CATEGORIES = ['educazione', 'intrattenimento', 'social media', 'notizie', 
              'shopping', 'tecnologia', 'professionale', 'gaming', 'sport', 'finanza', 'unknown']

age_group_patterns = {
    '13-17': {'gaming': 0.40, 'social media': 0.35, 'intrattenimento': 0.10, 'educazione': 0.05, 'notizie': 0.03, 'shopping': 0.03, 'tecnologia': 0.02, 'professionale': 0.00, 'sport': 0.01, 'finanza': 0.01, 'unknown': 0.00},
    '18-24': {'intrattenimento': 0.35, 'educazione': 0.25, 'social media': 0.20, 'gaming': 0.10, 'notizie': 0.03, 'shopping': 0.02, 'tecnologia': 0.02, 'professionale': 0.00, 'sport': 0.02, 'finanza': 0.01, 'unknown': 0.00},
    '25-35': {'professionale': 0.45, 'notizie': 0.20, 'tecnologia': 0.10, 'educazione': 0.10, 'intrattenimento': 0.05, 'social media': 0.05, 'shopping': 0.02, 'gaming': 0.01, 'sport': 0.01, 'finanza': 0.00, 'unknown': 0.01},
    '35-44': {'professionale': 0.40, 'notizie': 0.25, 'tecnologia': 0.10, 'educazione': 0.05, 'intrattenimento': 0.05, 'social media': 0.05, 'shopping': 0.05, 'gaming': 0.01, 'sport': 0.02, 'finanza': 0.00, 'unknown': 0.02},
    '45-54': {'notizie': 0.30, 'shopping': 0.20, 'finanza': 0.15, 'professionale': 0.10, 'educazione': 0.05, 'intrattenimento': 0.05, 'social media': 0.05, 'tecnologia': 0.03, 'gaming': 0.01, 'sport': 0.03, 'unknown': 0.03},
    '55+':   {'notizie': 0.35, 'shopping': 0.25, 'finanza': 0.15, 'educazione': 0.05, 'professionale': 0.05, 'intrattenimento': 0.05, 'social media': 0.05, 'tecnologia': 0.02, 'gaming': 0.00, 'sport': 0.02, 'unknown': 0.01}
}

age_group_probabilities = {'13-17': 0.15, '18-24': 0.20, '25-35': 0.25, '35-44': 0.20, '45-54': 0.10, '55+': 0.10}

def generate_synthetic_data(n_samples=5000):
    """
    Genera dati sintetici basati sulle percentuali di tempo per categoria.
    """
    samples = []
    for _ in range(n_samples):
        age_group = random.choices(list(age_group_probabilities.keys()),
                                    weights=age_group_probabilities.values(), k=1)[0]
        base_dist = age_group_patterns[age_group]
        alpha_params = [max(base_dist[cat] * 10, 0.001) for cat in CATEGORIES]
        proportions = np.random.dirichlet(alpha_params)
        sample = {f"{cat}_pct": prop for cat, prop in zip(CATEGORIES, proportions)}
        sample['age_group'] = age_group
        samples.append(sample)
    return pd.DataFrame(samples)

if __name__ == "__main__":
    # Inizializza SparkSession
    spark = SparkSession.builder.appName("AgeGroupPrediction").getOrCreate()
    spark.sparkContext.setLogLevel("ERROR")
    
    print("╔══════════════════════════════════════════════╗")
    print("║        ADDDESTRAMENTO MODELLO CON SPARK         ║")
    print("╚══════════════════════════════════════════════╝")
    
    print("[*] Generazione dati sintetici...")
    # Genera dati in Pandas e convertili in Spark DataFrame
    pdf = generate_synthetic_data(n_samples=5000)
    df = spark.createDataFrame(pdf)
    print("[+] Dati generati.")

    # Definisci le colonne di feature: tutte le colonne che finiscono con "_pct"
    feature_cols = [f"{cat}_pct" for cat in CATEGORIES]

    # Pipeline per convertire la variabile target in indice numerico
    label_indexer = StringIndexer(inputCol="age_group", outputCol="label", handleInvalid="keep")

    # Assembla le feature in un unico vettore
    assembler = VectorAssembler(inputCols=feature_cols, outputCol="features")

    # Classificatore: utilizziamo RandomForest per esempio (multi-classe)
    rf = RandomForestClassifier(featuresCol="features", labelCol="label", numTrees=200, seed=42)

    # (Opzionale) Convertitore inverso per le etichette (utile in fase di predizione)
    label_converter = IndexToString(inputCol="prediction", outputCol="predicted_age_group",
                                    labels=label_indexer.fit(df).labels)

    # Crea la pipeline Spark
    pipeline = Pipeline(stages=[label_indexer, assembler, rf, label_converter])

    print("[*] Addestramento del modello...")
    # Esegui il train/test split
    train_df, test_df = df.randomSplit([0.8, 0.2], seed=42)
    model = pipeline.fit(train_df)
    print("[+] Addestramento completato.")

    # Valuta il modello
    predictions = model.transform(test_df)
    evaluator = MulticlassClassificationEvaluator(labelCol="label", predictionCol="prediction", metricName="accuracy")
    accuracy = evaluator.evaluate(predictions)
    print("╔══════════════════════════════════════════════╗")
    print("║            RISULTATI DELLA VALUTAZIONE          ║")
    print("╚══════════════════════════════════════════════╝")
    print(f"► Accuracy: {accuracy*100:.2f}%")

    # Salva il modello addestrato
    model_path = "/opt/spark/apps/model-spark"
    print("[*] Salvataggio del modello in", model_path)
    model.write().overwrite().save(model_path)
    print("[+] Modello salvato con successo.")

    spark.stop()

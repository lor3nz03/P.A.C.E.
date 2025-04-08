import pychrome
import time
import tldextract
import logging
import json
import os
import threading
from websocket._exceptions import WebSocketConnectionClosedException
from fluent import sender as fluent_sender

# Riduci i messaggi di log indesiderati
logging.getLogger("websocket").setLevel(logging.CRITICAL)
logging.getLogger("pychrome").setLevel(logging.CRITICAL)

# Parametri
DEBOUNCE_THRESHOLD = 3    # Ignora aggiornamenti rapidi (< 3 secondi)
LOCK_TIME = 60            # Fissa il sito principale per LOCK_TIME secondi
STABILIZATION_DELAY = 2   # Ritardo per stabilizzare l'URL (in secondi)
LOG_FILE = "browsing_stats.json"  # Nome del file di log JSON (backup)
UPDATE_INTERVAL = 10      # Intervallo di aggiornamento in secondi per inviare dati a Fluentd

# Configurazione Fluentd
FLUENTD_TAG = "browsing.stats"
FLUENTD_HOST = "localhost"  
FLUENTD_PORT = 24224        # Porta predefinita di Fluentd

# Inizializza il logger Fluentd
fluentd_logger = fluent_sender.FluentSender(FLUENTD_TAG, host=FLUENTD_HOST, port=FLUENTD_PORT)

# Dizionario per tenere traccia dei tab:
# key = tab.id, value = { "num": int, "url": str, "start_time": float, "last_url": str, "last_url_time": float }
tab_info = {}
tab_counter = 0

# Lock per l'accesso thread-safe al dizionario tab_info
tab_info_lock = threading.Lock()

def log_site_visit(site, seconds, is_active=False):
    """
    Registra un sito visitato e il tempo trascorso in secondi.
    Invia i dati a Fluentd e salva nel file JSON come backup.
    
    :param site: Il dominio del sito
    :param seconds: Tempo trascorso in secondi
    :param is_active: Se True, il sito è ancora attivo
    """
    # Crea il record da inviare
    record = {
        "site": site,
        "seconds": seconds,
        "timestamp": time.time(),
        "status": "active" if is_active else "closed"
    }
    
    # Invia i dati a Fluentd
    if not fluentd_logger.emit('visit', record):
        print(f"Errore nell'invio dei dati a Fluentd: {fluentd_logger.last_error}")
        # Salva nel file JSON come backup in caso di errore
        save_to_json_backup(record)
    else:
        status = "attivo" if is_active else "chiuso"
        print(f"Dati inviati a Fluentd: {site} - {seconds} secondi - {status}")

def save_to_json_backup(record):
    """
    Salva un record nel file JSON come backup.
    """
    # Controlla se il file esiste e carica i dati esistenti
    data = []
    if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 0:
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            # Se il file è corrotto, creiamo un nuovo array vuoto
            data = []
    
    # Aggiungo il nuovo record
    data.append(record)
    
    # Salva i dati aggiornati
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"Dati salvati nel backup JSON: {record['site']} - {record['seconds']} secondi")

def get_main_domain(url):
    """
    Estrae il dominio principale dall'URL.
    Per i servizi Google, mantiene il sottodominio (es. docs.google.com).
    """
    extracted = tldextract.extract(url)
    if extracted.domain == "google" and extracted.subdomain:
        return f"{extracted.subdomain}.{extracted.domain}.{extracted.suffix}"
    return f"{extracted.domain}.{extracted.suffix}"

def is_valid_url(url):
    """
    Verifica se l'URL è valido (es. non è "about:" o incompleto).
    """
    return url and "." in url and not url.startswith("about:")

def is_google_search(url):
    """
    Verifica se l'URL è una ricerca su Google.
    """
    return "google.com/search" in url

def is_temporary_url(url):
    """
    Verifica se l'URL è temporaneo o di reindirizzamento.
    """
    temporary_domains = ["ogs.google.com", "www.google.com"]  # Se serve aggiungo altri domini temporanei qui
    return any(domain in url for domain in temporary_domains)

def make_handle_frame_navigated(tab):
    """
    Crea il callback per il tab:
      - Cattura solo l'URL principale della pagina quando viene navigata.
      - Ignora le ricerche su Google e gli URL temporanei.
    """
    def handle_frame_navigated(**kwargs):
        global tab_info, tab_counter
        frame = kwargs.get("frame", {})
        url = frame.get("url", "")
        if not is_valid_url(url) or is_google_search(url) or is_temporary_url(url):
            return

        new_domain = get_main_domain(url)
        now = time.time()
        tab_id = tab.id

        with tab_info_lock:
            # Se il tab non è ancora registrato, registra il nuovo URL
            if tab_id not in tab_info:
                tab_counter += 1
                tab_info[tab_id] = {
                    "num": tab_counter,
                    "url": new_domain,
                    "start_time": now,
                    "last_url": new_domain,
                    "last_url_time": now
                }
                print(f"TAB {tab_counter} aperta: {new_domain}")
                return

            record = tab_info[tab_id]
            current_domain = record["url"]

            # Se l'URL è cambiato, aggiorna il record solo dopo un ritardo di stabilizzazione
            if new_domain != record["last_url"]:
                record["last_url"] = new_domain
                record["last_url_time"] = now
                return

            # Se l'URL è stabile (nessun cambiamento per STABILIZATION_DELAY secondi), aggiorna il record
            if now - record["last_url_time"] >= STABILIZATION_DELAY and new_domain != current_domain:
                diff = int(now - record["start_time"])
                if diff < DEBOUNCE_THRESHOLD:
                    return
                else:
                    print(f"TAB {record['num']} chiusa: {current_domain} dopo {diff} secondi")
                    # Registra il sito chiuso e il tempo trascorso
                    if diff >= DEBOUNCE_THRESHOLD:
                        log_site_visit(current_domain, diff, is_active=False)
                    
                    record["url"] = new_domain
                    record["start_time"] = now
                    print(f"TAB {record['num']} aperta: {new_domain}")
    return handle_frame_navigated

def make_handle_page_loaded(tab):
    """
    Crea il callback per il caricamento della pagina.
    Questo si attiva quando una pagina completa il caricamento.
    """
    def handle_page_loaded(**kwargs):
        tab_id = tab.id
        with tab_info_lock:
            if tab_id not in tab_info:
                return
                
            # Ottieni l'URL attuale della pagina
            result = tab.Runtime.evaluate(expression="window.location.href")
            url = result.get("result", {}).get("value", "")
            
            if is_valid_url(url):
                new_domain = get_main_domain(url)
                now = time.time()
                record = tab_info[tab_id]
                current_domain = record["url"]
                
                if new_domain != current_domain:
                    diff = int(now - record["start_time"])
                    if diff >= DEBOUNCE_THRESHOLD:
                        print(f"TAB {record['num']} chiusa: {current_domain} dopo {diff} secondi")
                        # Registra il sito chiuso e il tempo trascorso
                        log_site_visit(current_domain, diff, is_active=False)
                        
                        record["url"] = new_domain
                        record["start_time"] = now
                        print(f"TAB {record['num']} aperta: {new_domain}")
                    
    return handle_page_loaded

def make_handle_document_updated(tab):
    """
    Crea il callback per l'aggiornamento del documento.
    Questo si attiva quando il documento principale cambia.
    """
    def handle_document_updated(**kwargs):
        # Attendi un breve periodo per permettere al documento di caricarsi
        time.sleep(0.5)
        
        tab_id = tab.id
        with tab_info_lock:
            if tab_id not in tab_info:
                return
                
            # Ottieni l'URL attuale dalla pagina
            result = tab.Runtime.evaluate(expression="window.location.href")
            url = result.get("result", {}).get("value", "")
            
            if is_valid_url(url) and not is_google_search(url) and not is_temporary_url(url):
                new_domain = get_main_domain(url)
                now = time.time()
                record = tab_info[tab_id]
                current_domain = record["url"]
                
                if new_domain != current_domain:
                    diff = int(now - record["start_time"])
                    if diff >= DEBOUNCE_THRESHOLD:
                        print(f"TAB {record['num']} chiusa: {current_domain} dopo {diff} secondi")
                        # Registra il sito chiuso e il tempo trascorso
                        log_site_visit(current_domain, diff, is_active=False)
                        
                        record["url"] = new_domain
                        record["start_time"] = now
                        print(f"TAB {record['num']} aperta: {new_domain}")
                    
    return handle_document_updated

def attach_to_tab(tab):
    """ Attacca il monitoraggio della navigazione e i callback per il tab. """
    try:
        tab.start()
        tab.Page.enable()
        tab.Runtime.enable()  # Abilitiamo il Runtime per poter valutare espressioni JavaScript
        tab.Page.frameNavigated = make_handle_frame_navigated(tab)
        
        # Aggiungi il rilevamento del caricamento della pagina
        tab.Page.loadEventFired = make_handle_page_loaded(tab)
        
        # Aggiungi il rilevamento dell'aggiornamento del documento
        tab.Page.documentUpdated = make_handle_document_updated(tab)
    except Exception as e:
        print(f"Errore durante l'attacco al tab: {e}")

def periodic_update():
    """
    Funzione eseguita in un thread separato che invia periodicamente
    aggiornamenti sui siti aperti a Fluentd.
    """
    while True:
        try:
            time.sleep(UPDATE_INTERVAL)
            
            with tab_info_lock:
                now = time.time()
                for tab_id, record in tab_info.items():
                    current_domain = record["url"]
                    elapsed = int(now - record["start_time"])
                    if elapsed >= DEBOUNCE_THRESHOLD:
                        # Invia aggiornamento per il sito ancora attivo
                        log_site_visit(current_domain, elapsed, is_active=True)
        except Exception as e:
            print(f"Errore durante l'aggiornamento periodico: {e}")

def main():
    
    #browser = pychrome.Browser(url="http://host.docker.internal:9222")
    browser = pychrome.Browser(url="http://localhost:9222")
    known_tabs = {}

    print("In ascolto degli URL principali in tempo reale...\n")
    print(f"Invio dati a Fluentd su {FLUENTD_HOST}:{FLUENTD_PORT} con tag {FLUENTD_TAG}")
    print(f"Aggiornamento periodico ogni {UPDATE_INTERVAL} secondi")
    
    # Avvia il thread per gli aggiornamenti periodici
    update_thread = threading.Thread(target=periodic_update, daemon=True)
    update_thread.start()
    
    try:
        while True:
            tabs = browser.list_tab()
            for tab in tabs:
                if tab.id not in known_tabs:
                    attach_to_tab(tab)
                    known_tabs[tab.id] = tab
            active_ids = {tab.id for tab in tabs}
            for tab_id in list(known_tabs.keys()):
                if tab_id not in active_ids:
                    with tab_info_lock:
                        if tab_id in tab_info:
                            record = tab_info[tab_id]
                            elapsed = int(time.time() - record["start_time"])
                            print(f"TAB {record['num']} chiusa: {record['url']} dopo {elapsed} secondi")
                            # Registra il sito chiuso e il tempo trascorso
                            if elapsed >= DEBOUNCE_THRESHOLD:
                                log_site_visit(record['url'], elapsed, is_active=False)
                            del tab_info[tab_id]
                    del known_tabs[tab_id]
            for tab in list(known_tabs.values()):
                try:
                    tab.wait(0.1)
                except WebSocketConnectionClosedException:
                    continue
                except Exception as e:
                    print(f"Errore durante l'attesa del tab: {e}")
                    continue
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nChiusura del programma.")
        # Registra eventuali tab ancora aperti prima di chiudere
        with tab_info_lock:
            for tab_id, record in list(tab_info.items()):
                elapsed = int(time.time() - record["start_time"])
                if elapsed >= DEBOUNCE_THRESHOLD:
                    log_site_visit(record['url'], elapsed, is_active=False)

if __name__ == "__main__":
    main()
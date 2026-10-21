"""
Ristorante Larossa - Reservations Sniper
Monitor automatico 100% gratuito per disponibilità tavoli (2 persone):
- "Turin Brunch" (Sabato e Domenica a pranzo)
- "Aperi Supper" (Sabato a cena)

Esecuzione singola (progettato per GitHub Actions / scheduler).
Memoria anti-spam persistente su 'seen_slots.json':
- Invia notifiche Telegram SOLO per slot NUOVI non ancora presenti in seen_slots.json.
- Rimuove automaticamente gli slot non più disponibili dal file.
"""

import os
import sys
import json
import re
import time
import random
import argparse
from datetime import datetime, date
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Carica variabili d'ambiente da file .env se presente
load_dotenv()

# Configurazione Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Endpoint Prenotazione Ristorante Larossa
BASE_URL = "https://larossa.prenota-web.it/prenotazioni/"
BOOKING_PAGE_URL = f"{BASE_URL}?iframe=1&lang=it&ristorante=default"
CALENDARIO_URL = f"{BASE_URL}calendario.asp"
CHECKPLACE_URL = f"{BASE_URL}checkplace.asp"

SEEN_SLOTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen_slots.json")

DAY_NAMES_IT = {
    0: "Lunedì",
    1: "Martedì",
    2: "Mercoledì",
    3: "Giovedì",
    4: "Venerdì",
    5: "Sabato",
    6: "Domenica"
}

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": BOOKING_PAGE_URL,
    "X-Requested-With": "XMLHttpRequest"
})


def send_telegram_message(text: str, token: str = TELEGRAM_BOT_TOKEN, chat_id: str = TELEGRAM_CHAT_ID) -> bool:
    """Invia un messaggio Telegram formattato in Markdown via HTTP POST."""
    if not token or not chat_id:
        print("[ERRORE] Token o Chat ID Telegram non configurati.", file=sys.stderr)
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }

    try:
        resp = SESSION.post(url, data=payload, timeout=15)
        resp_data = resp.json()
        if resp_data.get("ok"):
            print("[TELEGRAM] Notifica inviata con successo!")
            return True
        else:
            print(f"[ERRORE TELEGRAM] Risposta API non valida: {resp_data}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"[ERRORE TELEGRAM] Impossibile contattare l'API Telegram: {e}", file=sys.stderr)
        return False


def get_slots_for_date(date_str: str, servizio: str, attesa: str = "0", autoblocco: str = "S") -> list:
    """Interroga checkplace.asp per ottenere gli orari liberi per una data specifica."""
    params = {
        "data": date_str,
        "servizio": servizio,
        "posti": "2",
        "idristorante": "1",
        "lang": "it",
        "waitList": attesa,
        "setAutoblocco": autoblocco
    }
    try:
        r = SESSION.get(CHECKPLACE_URL, params=params, timeout=10)
        html = r.text
    except Exception as e:
        print(f"  [WARN] Errore verifica orari per {date_str} ({servizio}): {e}")
        return []

    soup = BeautifulSoup(html, "html.parser")

    # Parsing script inline per orari nascosti via jQuery (es. 19:00 o 21:00)
    hidden_hours = set()
    script_text = "\n".join(s.text for s in soup.find_all("script"))

    # Pattern 1: data-orario='...' ... .hide()
    for m in re.finditer(r'data-orario=[\'"]([0-9:]+)[\'"].*?\.hide\(\)', script_text, re.DOTALL):
        hidden_hours.add(m.group(1))

    # Pattern 2: var $var = ... data-orario="..." ... $var.hide()
    for m in re.finditer(r'(?:var|\$)\s*(\$?[a-zA-Z0-9_]+)\s*=.*?data-orario=[\'"]([0-9:]+)[\'"]', script_text):
        var_name = re.escape(m.group(1))
        ora = m.group(2)
        if re.search(var_name + r'\.hide\(\)', script_text):
            hidden_hours.add(ora)

    available_slots = []
    for btn in soup.find_all("div", class_="btn"):
        ora = btn.get("data-orario")
        if not ora or ora in hidden_hours:
            continue
        classes = btn.get("class", [])
        # Escludi slot in lista d'attesa (attesaH)
        if "attesaH" not in classes:
            available_slots.append(ora)

    return available_slots


def scan_reservations() -> list:
    """
    Effettua la scansione di tutti i mesi futuri disponibili per 2 persone:
    - 'P': Turin Brunch (Sabato e Domenica pranzo)
    - 'C': Aperi Supper (Sabato sera)
    Ritorna una lista di singoli slot normalizzati:
    [{"id": "Aperi Supper|26/12/2026|19:00", "service": "...", "date": "...", "weekday": "...", "time": "..."}]
    """
    current_slots = []

    today = date.today()
    curr_year = today.year
    curr_month = today.month

    services = [
        ("P", "brunch", "Turin Brunch"),
        ("C", "aperisupper", "Aperi Supper")
    ]

    for service_code, service_key, service_label in services:
        print(f"\n--- Scansione servizio: {service_label} ---")
        y = curr_year
        m = curr_month
        max_months = 6
        months_checked = 0

        while months_checked < max_months:
            params = {
                "idRistorante": "1",
                "PC": service_code,
                "posti": "2",
                "mese": str(m),
                "anno": str(y),
                "giorno": "",
                "lang": "it",
                "tipotavolo": "N",
                "bambini": "S",
                "neonati": "S",
                "idvoucher": "",
                "deadlinevoucher": ""
            }

            try:
                r = SESSION.get(CALENDARIO_URL, params=params, timeout=10)
                soup = BeautifulSoup(r.text, "html.parser")
            except Exception as e:
                print(f"[ERRORE] Caricamento calendario {m}/{y}: {e}")
                break

            stato = soup.find("input", id="statoapertura")
            stato_val = stato.get("value") if stato else ""
            if stato_val == "troppoFuturo":
                print(f"  Mese {m:02d}/{y}: prenotazioni non ancora aperte (troppoFuturo). Fine scansione.")
                break

            titolo_mese = soup.find("td", class_="mese")
            mese_txt = titolo_mese.text.strip() if titolo_mese else f"{m:02d}/{y}"

            tds = soup.find_all("td", attrs={"data-data": True})
            days_found_in_month = 0

            for td in tds:
                classes = td.get("class", [])
                # Il giorno deve essere aperto e futuro, escludendo lista d'attesa (attesa1)
                if "aperto" in classes and "futuro" in classes:
                    if "attesa1" in classes or td.get("data-attesa") == "1":
                        continue

                    data_str = td.get("data-data")
                    try:
                        dt = datetime.strptime(data_str, "%d/%m/%Y").date()
                    except ValueError:
                        continue

                    # Filtro servizi richiesti:
                    # Brunch: Sabato (5) o Domenica (6)
                    # Aperi Supper: Sabato (5)
                    weekday = dt.weekday()
                    is_target = False
                    if service_key == "brunch" and weekday in (5, 6):
                        is_target = True
                    elif service_key == "aperisupper" and weekday == 5:
                        is_target = True

                    if is_target:
                        slots = get_slots_for_date(data_str, service_code, attesa="0", autoblocco="S")
                        if slots:
                            days_found_in_month += 1
                            date_formatted = dt.strftime("%d/%m/%Y")
                            weekday_name = DAY_NAMES_IT[weekday]
                            print(f"  [DISPONIBILE] {service_label} | {weekday_name} {date_formatted} | Orari: {', '.join(slots)}")
                            for s in slots:
                                slot_id = f"{service_label}|{date_formatted}|{s}"
                                current_slots.append({
                                    "id": slot_id,
                                    "service": service_label,
                                    "date": date_formatted,
                                    "weekday": weekday_name,
                                    "time": s
                                })

            if days_found_in_month == 0:
                print(f"  Mese {mese_txt}: nessun tavolo libero per i criteri selezionati.")

            # Verifica freccia prossimo mese
            right_arrow = soup.find("td", class_="text-right")
            if not right_arrow or "attivo" not in right_arrow.get("class", []):
                print(f"  Mese {mese_txt}: freccia prossimo mese non attiva. Fine scansione.")
                break

            m += 1
            if m > 12:
                m = 1
                y += 1
            months_checked += 1

    return current_slots


def load_seen_slots() -> list:
    """Carica gli slot salvati in precedenza dal file seen_slots.json."""
    if os.path.exists(SEEN_SLOTS_FILE):
        try:
            with open(SEEN_SLOTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception as e:
            print(f"[WARN] Impossibile leggere seen_slots.json: {e}")
    return []


def save_seen_slots(slots: list):
    """Salva la lista corrente di slot disponibili in seen_slots.json."""
    try:
        # Ordina per data (convertita in oggetto date per ordine cronologico corretto) e orario
        def sort_key(s):
            try:
                dt = datetime.strptime(s.get("date", ""), "%d/%m/%Y")
            except Exception:
                dt = datetime.min
            return (s.get("service", ""), dt, s.get("time", ""))

        sorted_slots = sorted(slots, key=sort_key)
        with open(SEEN_SLOTS_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted_slots, f, ensure_ascii=False, indent=2)
        print(f"[CACHE] Aggiornato {SEEN_SLOTS_FILE} con {len(sorted_slots)} slot correnti.")
    except Exception as e:
        print(f"[ERRORE] Impossibile salvare {SEEN_SLOTS_FILE}: {e}")


def format_telegram_message(new_slots: list, is_test: bool = False, total_current: int = 0) -> str:
    """Formatta i nuovi slot rilevati in un messaggio Markdown per Telegram."""
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")

    if not new_slots:
        if is_test:
            return (
                f"🤖 *Ristorante Larossa - Reservations Sniper*\n"
                f"Test di notifica eseguito con successo!\n\n"
                f"Stato attuale: *{total_current} slot liberi totali* in monitoraggio.\n"
                f"_Nessun nuovo slot rispetto all'ultimo controllo._\n\n"
                f"👉 [Verifica sul sito]({BOOKING_PAGE_URL})\n"
                f"_Controllo: {now_str}_"
            )
        return ""

    # Raggruppa i nuovi slot per Servizio e Data
    grouped = {}
    for slot in new_slots:
        srv = slot["service"]
        d = (slot["weekday"], slot["date"])
        grouped.setdefault(srv, {}).setdefault(d, []).append(slot["time"])

    lines = [
        "🚨 *LAROSSA - NUOVI TAVOLI DISPONIBILI!* 🚨",
        f"Trovata nuova disponibilità per *2 persone*!\n"
    ]

    if "Turin Brunch" in grouped:
        lines.append("🥞 *TURIN BRUNCH (Sabato/Domenica Pranzo)*:")
        for (wday, d_str), times in grouped["Turin Brunch"].items():
            times_str = ", ".join(sorted(times))
            lines.append(f"• *{wday} {d_str}*: `{times_str}`")
        lines.append("")

    if "Aperi Supper" in grouped:
        lines.append("🍸 *APERI SUPPER (Sabato Cena)*:")
        for (wday, d_str), times in grouped["Aperi Supper"].items():
            times_str = ", ".join(sorted(times))
            lines.append(f"• *{wday} {d_str}*: `{times_str}`")
        lines.append("")

    lines.append(f"👉 [PRENOTA SUBITO SU PRENOTA-WEB]({BOOKING_PAGE_URL})")
    lines.append(f"_Rilevato il: {now_str}_")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Larossa Reservations Sniper (GitHub Actions Ready)")
    parser.add_argument("--test", action="store_true", help="Invia comunque un messaggio diagnostico a Telegram")
    parser.add_argument("--force", action="store_true", help="Invia notifica per tutti gli slot trovati ignorando lo storico")
    parser.add_argument("--quiet", action="store_true", help="Non inviare messaggi Telegram, stampa solo a console")
    parser.add_argument("--random-delay", nargs=2, type=int, metavar=("MIN", "MAX"), help="Pausa casuale in secondi tra MIN e MAX prima di avviare la scansione")
    args = parser.parse_args()

    if args.random_delay:
        min_s, max_s = args.random_delay
        if max_s >= min_s >= 0:
            sleep_s = random.randint(min_s, max_s)
            print(f"[JITTER] Attesa casuale di {sleep_s} secondi prima della scansione...")
            time.sleep(sleep_s)

    print("=" * 60)
    print(" RISTORANTE LAROSSA - RESERVATIONS SNIPER")
    print(f" Data controllo: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print("=" * 60)

    # 1. Carica slot memorizzati in precedenza
    seen_slots = load_seen_slots()
    seen_ids = {s["id"] for s in seen_slots if isinstance(s, dict) and "id" in s}
    print(f"[CACHE] Slot precedentemente noti in seen_slots.json: {len(seen_ids)}")

    # 2. Effettua la scansione in tempo reale
    current_slots = scan_reservations()
    current_ids = {s["id"] for s in current_slots}
    print("\n" + "=" * 60)
    print(f"Riepilogo scansione: {len(current_slots)} slot liberi totali trovati.")
    print("=" * 60)

    # 3. Calcola i nuovi slot (presenti ora ma non in seen_ids)
    if args.force:
        new_slots = current_slots
    else:
        new_slots = [s for s in current_slots if s["id"] not in seen_ids]

    # Slot rimossi (erano noti, ma non sono più disponibili)
    removed_ids = seen_ids - current_ids
    if removed_ids:
        print(f"[INFO] {len(removed_ids)} slot non sono più disponibili e vengono rimossi da seen_slots.json.")

    # 4. Invia notifica Telegram SOLO se ci sono nuovi slot o flag --test
    should_send = False
    if args.test:
        should_send = True
    elif len(new_slots) > 0 and not args.quiet:
        should_send = True
        print(f"[ALLERTA] Rilevati {len(new_slots)} NUOVI slot liberi! Preparazione notifica Telegram...")
    else:
        print("[INFO] Nessun nuovo slot rilevato. Nessun messaggio Telegram da inviare.")

    if should_send and not args.quiet:
        msg = format_telegram_message(new_slots, is_test=args.test, total_current=len(current_slots))
        if msg:
            send_telegram_message(msg)

    # 5. Aggiorna seen_slots.json se ci sono state modifiche (nuovi slot o slot rimossi)
    # In questo modo, se uno slot torna non disponibile, viene rimosso dal file;
    # se si rilibera in futuro, verrà nuovamente rilevato come nuovo!
    if seen_ids != current_ids or not os.path.exists(SEEN_SLOTS_FILE):
        save_seen_slots(current_slots)
    else:
        print("[CACHE] Nessuna variazione negli slot disponibili. seen_slots.json invariato.")


if __name__ == "__main__":
    main()

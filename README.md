# 🎯 Ristorante Larossa - Reservations Sniper

Monitor automatico **100% gratuito** per verificare 24/7 la disponibilità di tavoli da **2 persone** al **Ristorante Larossa** (Torino) per i seguenti servizi:
* **Turin Brunch**: Sabato e Domenica a pranzo (`servizio = 'P'`).
* **Aperi Supper**: Sabato a cena (`servizio = 'C'`).

Ogni volta che uno slot viene liberato o aperto, lo script invia una notifica immediata su Telegram con link diretto alla prenotazione.

---

## 🚀 Funzionalità Principali

* **Esecuzione Singola & Cloud Ready**: Progettato specificamente per girare ogni 15 minuti su **GitHub Actions** (100% gratuito, senza bisogno di tenere il PC acceso).
* **Memoria Anti-Spam (`seen_slots.json`)**: Salva lo storico degli slot liberi noti. Invia notifiche Telegram **SOLO** per i nuovi slot non ancora notificati.
* **Auto-Rimozione & Ri-Allerta**: Se un tavolo viene prenotato e non è più disponibile, viene automaticamente rimosso da `seen_slots.json`. Qualora dovesse liberarsi di nuovo in futuro (disdetta), scatterà una nuova notifica immediata!
* **Parsing Intelligente**: Rileva le disponibilità effettive distinguendole dalla lista d'attesa (`attesaH`) e filtrando gli orari nascosti dinamicamente dagli script JS del ristorante.

---

## ⚙️ Configurazione Telegram

I seguenti Secret sono configurati nella repository GitHub:
* `TELEGRAM_BOT_TOKEN`: Token del bot Telegram.
* `TELEGRAM_CHAT_ID`: ID della chat o del canale Telegram ricevente.

Per l'esecuzione locale, è sufficiente compilare il file `.env`:
```env
TELEGRAM_BOT_TOKEN=tuo_bot_token_qui
TELEGRAM_CHAT_ID=tuo_chat_id_qui
```

---

## 💻 Esecuzione Locale

```bash
# Installa le dipendenze
pip install -r requirements.txt

# Controllo standard (notifica solo nuovi slot)
python monitor.py

# Forza l'invio della notifica ignorando lo storico
python monitor.py --force

# Test diagnostico bot Telegram
python monitor.py --test

# Modalità silenziosa (solo log a video, niente Telegram)
python monitor.py --quiet
```

---

## 🤖 Automazione GitHub Actions

Il workflow `.github/workflows/monitor.yml` si attiva:
1. Automaticamente ogni 15 minuti tramite cron (`*/15 * * * *`).
2. Manualmente via `workflow_dispatch` (tasto "Run workflow" su GitHub o comando `gh workflow run monitor.yml`).
3. Se rileva variazioni negli slot, aggiorna e committa automaticamente `seen_slots.json` sulla repository.

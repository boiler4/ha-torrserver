# TorrServer per Home Assistant

[English](README.md) · [Italiano](README.it.md) · [Русский](README.ru.md)

Integrazione locale e in sola lettura per monitorare
[YouROK/TorrServer](https://github.com/YouROK/TorrServer) da Home Assistant.
Non aggiunge, elimina, arresta o modifica torrent e impostazioni TorrServer.

La versione stabile corrente è `0.3.0`. `0.4.0-beta.4` è una prerelease
facoltativa per provare autonomia e previsione delle interruzioni.

## Funzioni principali

- Ricerca automatica locale consigliata oppure URL manuale.
- Autenticazione Basic, HTTPS e certificati autofirmati.
- Velocità download/upload, media streaming sensibile alla cache, bitrate,
  torrent/riproduzioni attive, peer, seed e diagnostica completa.
- Salute streaming nativa: `protected` (Buono), `stable` (Stabile),
  `insufficient` (Non sufficiente), `measuring`, `idle` e `unknown`.
- Secondi di buffer riproducibile, soglie, margini e ritardo configurabili.
- Analisi sperimentale del bitrate reale tramite `/ffp` di TorrServer.
- Interfaccia in italiano, inglese e russo; diagnostica, System Health e Repairs.

## Installazione HACS

TorrServer è incluso nel catalogo community predefinito di HACS.

1. Apri HACS e cerca **TorrServer**.
2. Scarica l'integrazione, riavvia Home Assistant e aggiungila da
   **Impostazioni → Dispositivi e servizi**.
3. HACS propone la stabile. Per provare questa beta, abilita le prerelease nel
   selettore delle versioni e scegli esplicitamente `v0.4.0-beta.4`.

Se il catalogo non è ancora aggiornato, aggiungi
`https://github.com/boiler4/ha-torrserver` come repository personalizzato di tipo
**Integrazione**. La presenza in HACS non significa inclusione in HA Core.

## Ricerca e autenticazione

La ricerca automatica parte solo quando l’utente la richiede. Controlla le reti
IPv4 abilitate di Home Assistant, al massimo 512 host e una `/24` per reti più
ampie. Usa soltanto 8090/HTTP e 8091/HTTPS oppure una singola porta personalizzata.
Non esiste scansione periodica.

Durante la ricerca non vengono mai inviate credenziali. Un server che risponde
401/403 viene indicato come protetto e nome utente/password vengono usati solo
dopo averlo selezionato. Evita Basic Auth su HTTP in reti non affidabili. Per un
HTTPS affidabile con certificato autofirmato puoi disattivare esplicitamente la
verifica SSL.

## Come funziona la salute streaming

La beta.4 usa **reader-v2** come modello autorevole predefinito. Combina posizione
del lettore TorrServer, pezzi consecutivi completati, consumo del lettore,
velocità media e andamento del buffer. Un torrent soltanto in seed, senza lettore
cache attivo, non peggiora la salute dello streaming.

- Se il resto del file è già in cache, lo stato resta **Buono** (`protected`)
  anche con download a zero. La sola occupazione cache non prova la continuità.
- Avvio e ripresa raccolgono nuovi campioni prima di abilitare il rischio. Un
  seek rilevato o una pausa confermata azzerano rischio ed ETA precedenti; alla
  ripresa si misura nuovamente, senza riutilizzare le vecchie velocità.
- Deficit persistenti e svuotamento previsto del buffer possono ancora generare
  un allarme dopo la fase iniziale di misurazione.
- Entity ID e stati tecnici restano compatibili. Gli attributi espongono modello,
  fase, condizione, buffer, confidenza e motivazione.
- L'opzione reader-v2 è autorevole, non solo diagnostica. Disattivandola si usa
  il modello precedente; le chiavi salvate `stream_shadow_*` restano compatibili.

Le fasi sono dedotte dall'attività del server: l'integrazione non legge il tasto
pausa né la schermata di caricamento del player. La previsione è una stima,
non una garanzia. Gli allarmi iniziali restano in valutazione sul campo.

## Semaforo nativo

Non servono card HACS aggiuntive. Usa l’esempio YAML completo nel
[README inglese](README.md#native-traffic-light-dashboard): tre Tile condizionali
con `mdi:traffic-light` e colori blu, giallo e rosso. L'ID dell'entità rimane
stabile; dalla versione 0.3.0 i vecchi stati colore usano nomi semantici.

## Autonomia e previsione interruzione (beta)

**Autonomia streaming** indica i secondi consecutivi realmente riproducibili
davanti al lettore. La nuova previsione mostra `Sostenibile`, `Buffer in
esaurimento`, `Rischio interruzione`, `Misurazione` o `Sconosciuta`. Il tempo
stimato all'interruzione compare soltanto quando il buffer misurato diminuisce;
non viene inventato se è stabile o cresce.

Per impostazione predefinita il rischio viene candidato entro 60 secondi e deve
persistere 15 secondi; entrambe le soglie sono modificabili. Dopo la fase iniziale di misurazione, sotto cinque secondi
il rischio può bypassare la conferma ordinaria. Il sensore binario **Rischio interruzione streaming** è
utilizzabile in notifiche e automazioni native.

Il riepilogo della sessione contiene buffer minimo, velocità media, tempo nello
stato Non sufficiente, durata ed eventi di rischio. Rimane soltanto nella memoria
di Home Assistant e si azzera alla fine della riproduzione o al riavvio. È una
previsione del rischio lato TorrServer, non la conferma che il player abbia
mostrato una schermata di buffering.

## Bitrate sperimentale e `ffprobe`

L’opzione è disattivata di default. Home Assistant interroga l’endpoint `/ffp`
già presente in TorrServer dopo il buffer iniziale, con timeout e cache limitata
solo in memoria. Gli errori transitori vengono ritentati dopo 15, 30, 60, 120 e
al massimo 300 secondi; l’avviso Repairs compare solo dopo tre errori
consecutivi. Diagnostica espone il tipo di errore e il prossimo tentativo senza
identificatori del torrent.

I valori misurati espongono `bit_rate_source` e `estimated: false`. Durante
l’attesa o in caso di errore, il monitoraggio continua con una stima
esplicitamente indicata. Nei torrent multi-file il fallback usa la dimensione
del file attivo, non quella dell’intero torrent. L’integrazione non modifica
TorrServer o la riproduzione.

TorrServer deve poter eseguire `ffprobe`. Nel sistema Debian/Linux verificato:

```bash
sudo apt update
sudo apt install ffmpeg
command -v ffprobe
sudo ln -s /usr/bin/ffprobe /opt/torrserver/ffprobe
```

Verifica sempre il percorso reale e non sovrascrivere file esistenti. In Docker
serve un’immagine che contenga ffprobe; su Windows `ffprobe.exe`; su macOS il
pacchetto ffmpeg normalmente lo include. L’integrazione non esegue mai questi
passi amministrativi.

### Log opzionale per osservare la salute streaming

Per una breve finestra diagnostica abilita il debug solo per l’integrazione:

```yaml
logger:
  logs:
    custom_components.torrserver: debug
```

Durante una lettura reale viene emesso un JSON `stream_health_sample` per ogni
poll, seguito da `stream_health_idle` alla fine. Contiene decisioni di salute e
forecast, buffer e trend, margine di velocità, provenienza del bitrate,
cache/peer/sessione e retry ffprobe. Non contiene titoli, hash, link, percorsi,
URL, indirizzi o credenziali. Disabilita il debug dopo aver raccolto abbastanza
sessioni.

## Bug e privacy

Dalla pagina dell’integrazione scarica **Diagnostica**, controlla il JSON e
allegalo manualmente al modulo **New issue** su GitHub. Credenziali, hash, titoli,
nomi, percorsi, poster e dati dei file sono oscurati; nessun dato viene caricato
automaticamente. I moduli guidati richiedono lingua, versione, passaggi, risultato
atteso e log.

Licenza MIT. Progetto indipendente, non ufficiale TorrServer/Home Assistant.

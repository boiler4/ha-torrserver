# TorrServer per Home Assistant

[English](README.md) · [Italiano](README.it.md) · [Русский](README.ru.md)

Integrazione locale e in sola lettura per monitorare
[YouROK/TorrServer](https://github.com/YouROK/TorrServer) da Home Assistant.
Non aggiunge, elimina, arresta o modifica torrent e impostazioni TorrServer.

> `0.3.0-beta.4` è una versione di test e rimane sulla branch beta fino alla
> conclusione delle verifiche.

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

Finché il repository non è nel catalogo HACS predefinito:

1. Apri HACS → menu → **Repository personalizzati**.
2. Inserisci `https://github.com/boiler4/ha-torrserver` come **Integrazione**.
3. Installa TorrServer, riavvia Home Assistant e aggiungi l’integrazione da
   **Impostazioni → Dispositivi e servizi**.

Durante i test seleziona esplicitamente la versione beta.

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

Contano soltanto i torrent con un lettore cache TorrServer realmente attivo: un
torrent soltanto in seed non peggiora lo stato. Con più riproduzioni viene
mostrato lo stato peggiore e gli attributi riportano i conteggi separati.

Il segnale principale sono i secondi realmente disponibili davanti al lettore,
calcolati contando i `Pieces` consecutivi marcati `Completed` da `/cache` fino
al primo buco e convertendoli con il bitrate. Il pezzo corrente viene escluso
perché TorrServer non espone l'offset esatto del lettore al suo interno:

- **Buono** (stato tecnico `protected`) con almeno 60 secondi consecutivi o file
  completo;
- **Stabile** con almeno 15 secondi oppure buffer basso che riesce a recuperare;
- **Non sufficiente** sotto 15 secondi quando velocità e andamento del buffer
  non riescono a sostenere la riproduzione;
- **Misurazione** quando mancano ancora dati sufficienti.

La modalità buffer è separata: `full`, `preloading`, `stable`, `draining`,
`recovering` o `unknown`. `full` indica che il buffer consecutivo ha raggiunto
la soglia Buono; l'occupazione della cache è solo diagnostica e non rende più
lo stato Buono da sola. Le impostazioni predefinite sono 15/60 secondi, margini
velocità 0%/10%, media 15 secondi e ritardo di peggioramento 15 secondi. Tutti
questi valori sono modificabili. Sotto 5 secondi o senza sorgenti utilizzabili
lo stato peggiora immediatamente.

Negli attributi trovi secondi, modalità e andamento buffer, velocità in Mbps,
bitrate, soglie, occupazione cache, pezzi consecutivi completati, campioni, peer,
seed, motivazione e transizione pendente.

## Semaforo nativo

Non servono card HACS aggiuntive. Usa l’esempio YAML completo nel
[README inglese](README.md#native-traffic-light-dashboard): tre Tile condizionali
con `mdi:traffic-light` e colori blu, giallo e rosso. L'ID dell'entità rimane
stabile; gli stati beta passano dai vecchi colori ai nuovi nomi semantici.

## Bitrate sperimentale e `ffprobe`

L’opzione è disattivata di default. Home Assistant interroga l’endpoint `/ffp`
già presente in TorrServer al massimo una volta per file, con timeout e cache
solo in memoria. Non modifica TorrServer. Se fallisce, usa una stima conservativa
e crea un avviso Repairs.

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

## Bug e privacy

Dalla pagina dell’integrazione scarica **Diagnostica**, controlla il JSON e
allegalo manualmente al modulo **New issue** su GitHub. Credenziali, hash, titoli,
nomi, percorsi, poster e dati dei file sono oscurati; nessun dato viene caricato
automaticamente. I moduli guidati richiedono lingua, versione, passaggi, risultato
atteso e log.

Licenza MIT. Progetto indipendente, non ufficiale TorrServer/Home Assistant.

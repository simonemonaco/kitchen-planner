# Kitchen Planner

Webapp Flask per gestire i prodotti disponibili in frigo e dispensa, con scadenza precisa oppure stimata, e una lista della spesa collegata all'inventario.

## Funzioni

- Inventario separato tra frigo e dispensa.
- Tabella `item_prior` per le informazioni stabili del prodotto: nome, categoria, quantita' tipica, unita' tipica, scadenza tipica in giorni, immagine, fonte e note.
- `inventory_items` e `shopping_items` sono realizzazioni dinamiche di un `item_prior`.
- I form operativi chiedono solo nome prodotto, quantita', unita', destinazione e, per l'inventario, data di scadenza.
- Scadenza precompilata dalla scadenza tipica del prior quando aggiungi un prodotto all'inventario.
- Lookup automatico dell'immagine al primo inserimento tramite Open Food Facts.
- Seed automatico dei prior iniziali: Mozzarella, Pasta, Riso, Farro, Melanzane, Mele, Pere, Fragole.
- Nei form di inserimento puoi scegliere un prodotto prior dalla barra nome con dropdown; se scrivi un nome non selezionato, viene creato un nuovo prior.
- Pulsante `Finito` che rimuove un prodotto dall'inventario e lo aggiunge alla lista della spesa.
- Pulsante `Aggiungi scontrino` per caricare una foto, leggere le righe prodotto con OCR e aggiungerle alla cucina dopo revisione.
- Lista della spesa compilabile anche manualmente.
- Pulsante `Acquistato` che crea automaticamente il prodotto in frigo o dispensa, rimuove la voce dalla lista e registra lo storico.
- Tabella `items_history` con timestamp, costo opzionale, quantita', unita' e destinazione dell'acquisto.
- Riepilogo con prodotti totali, prior prodotto, prodotti in frigo, in dispensa, scaduti, in scadenza e da comprare.
- Sezione `Impostazioni` per vedere e modificare il database dei prodotti prior.
- Categoria prior vincolata a: Carne, Pesce, Uova, Latticini, Formaggi, Cereali, Legumi, Pasta, Verdura, Frutta, Dolci, Altro.

## Database

Il database SQLite viene creato automaticamente in `instance/kitchen.sqlite`.

- `item_prior`: anagrafica stabile dei prodotti. La colonna `picture` contiene il link all'immagine del prodotto, `default_location` contiene la destinazione predefinita.
- `inventory_items`: scorte reali presenti in casa, collegate a `item_prior` tramite `item_prior_id`.
- `shopping_items`: prodotti da comprare, collegati a `item_prior` tramite `item_prior_id`.
- `items_history`: acquisti registrati quando una voce della lista spesa viene indicata come acquistata.

Se esiste un database creato con la versione precedente, l'app migra automaticamente `inventory_items` e `shopping_items` al nuovo modello.

## Immagini

Quando viene creato un nuovo `item_prior` senza immagine manuale, l'app cerca un prodotto compatibile su Open Food Facts e salva il primo `image_front_url` disponibile in `picture`.
Per alcuni ingredienti generici il progetto usa un fallback TheMealDB con URL pubblici per immagini di ingredienti.

Puoi riprovare il popolamento immagini dei prior iniziali con:

```bash
python3 scripts/populate_prior_images.py
```

Per evitare chiamate esterne nei test puoi disattivare il lookup con la config Flask `ENABLE_FOOD_IMAGE_LOOKUP=False`.

## OCR scontrini

Il flusso scontrino usa `tesseract.js` direttamente nel browser (WebAssembly), quindi non richiede il binario di sistema `tesseract`.
L'app cerca le righe prodotto dopo la riga che contiene `vendita` e `prestazione`, ignora la colonna IVA e si ferma alla riga che inizia con `SUBTOTALE`.

Note operative:

```bash
pip install -r requirements.txt
```

Per l'OCR e' necessaria una connessione Internet al primo utilizzo, per scaricare gli asset runtime/language del motore JS.

## Avvio

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Apri `http://127.0.0.1:5000`.

## Test

```bash
python3 -m unittest
```

# ADE 2026 – Abrechnung

Eine kleine Splitwise-Alternative für euer ADE-Wochenende. Alles steckt in einer
einzigen Datei (`index.html`) und läuft auf dem Handy wie eine App.

**Was sie kann**

- Ausgaben eintragen: Betrag, wofür, wann und wer bezahlt hat (auch mehrere Zahler).
- Aufteilen wie bei Splitwise: **gleich** auf ausgewählte Leute, mit **festen Beträgen**
  oder nach **Anteilen** (z. B. 2 : 1 : 1, wenn jemand doppelt getrunken hat).
- **Wer zahlt wem?** Höchstens drei Überweisungen bei vier Leuten. Rückzahlungen lassen
  sich eintragen, mit PayPal.me-Namen gibt es direkt einen PayPal-Button.
- Kontostand pro Person, Ausgaben nach Kategorie, „Abrechnung teilen“ für WhatsApp.
- Centgenau: Restcents werden reihum verteilt, Beträge wie `12,50`, `1.234,56` oder `20+8,50` gehen.
- Backup als Datei, keine Anfragen an Google & Co., für Suchmaschinen gesperrt.

Es gibt zwei Wege, die Seite zu betreiben. Variante A ist in fünf Minuten erledigt,
Variante B gibt euch Live-Sync wie bei Splitwise.

## Variante A: Einfach hochladen (ohne Server)

1. **Namen eintragen (empfohlen):** `index.html` in einem Editor öffnen und oben bei
   `CONFIG` eure vier Namen eintragen:

   ```js
   people: ['Alex', 'Ben', 'Chris', 'Dana'],   // eure echten Namen
   ```

   Dann haben alle von Anfang an dieselben Namen. Ohne das fragt die App beim ersten Öffnen danach.
2. Die Datei als **`ade/index.html`** auf yland.media hochladen, also neben die
   anderen Seiten in einen neuen Ordner `ade`.
3. **https://yland.media/ade/** öffnen und den Link in eure Gruppe schicken.

**So bleibt ihr auf demselben Stand:** Jede:r trägt auf dem eigenen Handy ein. Danach
tippt man auf **„Teilen“** und schickt den Link in die WhatsApp-Gruppe. Wer den Link
öffnet, bekommt alle Einträge dazu. Es wird nichts doppelt gezählt oder überschrieben,
auch Löschungen kommen mit. Unter „Gruppe → Abgleich“ steht ein **Datenstand-Code**.
Haben alle denselben Code, haben alle denselben Stand.

> Tipp: Damit es kein Durcheinander gibt, legst am besten du die Gruppe an und schickst
> den ersten Link herum. Die anderen öffnen diesen Link, bevor sie selbst etwas eintragen.

## Variante B: Live-Sync mit Mini-Server (Docker)

Wenn die Seite von `server.js` ausgeliefert wird, merkt die App das automatisch. Alle
sehen dann jede Änderung nach wenigen Sekunden, ohne Links hin und her zu schicken.
Die Daten liegen auf deinem Server in einer JSON-Datei.

1. Den Ordner `ade-abrechnung` auf den Server kopieren.
2. Einen Zugangscode festlegen:

   ```bash
   cd ade-abrechnung
   echo "GROUP_KEY=$(openssl rand -hex 6)" > .env
   docker compose up -d --build
   ```

   Die App läuft jetzt auf Port `8088`.
3. Im Reverse Proxy freischalten, zum Beispiel im **Nginx Proxy Manager**:
   - **Unter yland.media/ade:** beim Proxy-Host `yland.media` → *Custom Locations* →
     Location `/ade`, Forward Hostname/IP = IP des Servers, Port `8088`.
   - **Oder als Subdomain** `ade.yland.media`: DNS-Eintrag anlegen, neuen Proxy-Host auf
     Port `8088` und im Tab *SSL* ein Let's-Encrypt-Zertifikat anfordern.

   Mit einem normalen nginx reicht `location /ade/ { proxy_pass http://127.0.0.1:8088; }`.
4. Den **Einladungslink** in die Gruppe schicken (der Code steckt darin):
   `https://yland.media/ade/#k=DEIN_CODE`. In der App unter „Gruppe“ gibt es dafür auch
   einen Button.

Läuft der Proxy Manager selbst in Docker, kann der Container auch in dessen Netzwerk
(siehe Kommentar in `docker-compose.yml`). Dann braucht es den Port `8088` nach außen nicht.
Nach Änderungen an `index.html`: `docker compose up -d --build`.

Ohne Docker geht es auch direkt mit Node.js ab Version 18:
`GROUP_KEY=geheim PORT=8088 node server.js`.

## Gut zu wissen

- **„Wer bist du?“** wird nur auf dem jeweiligen Gerät gespeichert. Dann zeigt die App
  „du bekommst noch …“ bzw. „du schuldest …“.
- **Daten:** Variante A speichert im Browser und in den geteilten Links, Variante B
  zusätzlich in `/data/ade.json` (Docker-Volume `ade-daten`). Ein Backup gibt es jederzeit
  unter „Gruppe → Als Datei sichern“.
- **Optional:** `publicUrl` in `CONFIG` setzen (z. B. `'https://yland.media/ade/'`), falls
  Teilen-Links immer auf diese Adresse zeigen sollen.
- Die Schrift Space Grotesk (SIL Open Font License) ist eingebettet, deshalb sind keine
  externen Dateien nötig.

## Tests

```bash
node --test
```

Die Server-Tests laufen mit Node allein. Ist [Playwright](https://playwright.dev)
installiert, laufen zusätzlich die Browser-Tests (Rechenlogik, kompletter Durchlauf,
Abgleich per Link und per Server).

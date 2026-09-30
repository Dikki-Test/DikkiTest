# Regionale Web- & Social-Agentur – Lead-Finder

Findet **Handwerksbetriebe** und **Immobilienmakler** in einer Region und prüft
automatisch, was man ihnen verkaufen kann:

| Zielgruppe | Was geprüft wird | Mögliches Angebot |
|---|---|---|
| alle | Gibt es eine Website? Ist sie erreichbar? | Website-Neubau |
| alle | Website-Qualität: HTTPS, Handy-tauglich, Impressum/Datenschutz, klickbare Telefonnummer, Kontaktformular, © Jahr, veraltete Technik, Baukasten | Relaunch / Optimierung |
| alle | Instagram vorhanden? Wie aktiv (Posts/30 Tage, letzter Post, Engagement)? | Social-Media-Aufbau / -Betreuung |
| Makler | Fotoqualität der Objektfotos (Auflösung, Helligkeit, Schärfe, Handy-Hochformat, optional KI-Gutachten) | Immobilienfotografie |
| Makler | 360°-/3D-Rundgänge (Matterport, Ogulo, immoviewer, FeelEstate, 3DVista, Kuula, Giraffe360 …) | 360°-Rundgänge |
| Makler | (Virtuelles/KI-)Home-Staging, Drohnen, Video, Makler-CRM (onOffice, FLOWFACT, Propstack …) | KI-Staging, Drohne, Video |

Am Ende steht pro Betrieb ein **Lead-Score (0–100)**, eine **Priorität A/B/C**,
die konkreten **Chancen mit Begründung** und ein **Pitch-Satz** für den Erstkontakt.

## Das Konzept (überarbeitet)

1. **Finden, nicht blind scrapen.** Betriebe kommen aus offiziellen Quellen:
   OpenStreetMap (kostenlos) und optional die Google Places API. Google ist
   deutlich vollständiger und der wichtigste Baustein für den Punkt „hat keine
   Website“: Fehlt dort `websiteUri`, ist das ein starkes Signal. Aus OSM
   allein ist „keine Website“ nur ein Verdacht (im CSV gekennzeichnet).
   Gelbe Seiten, ImmoScout24 & Co. werden nicht gescrapt (Nutzungsbedingungen,
   Bot-Schutz).
2. **Auditieren – nur öffentliche Firmen-Websites**, höflich: eigener
   User-Agent, `robots.txt` wird beachtet, 1 Anfrage/Sekunde pro Host.
3. **Makler-Tiefenprüfung:** Startseite → Objektübersicht → 2–3 Exposés.
   Dort liegen die echten Objektfotos, Rundgang-Einbettungen und Staging-Hinweise.
   Die Fotoanalyse ist eine Heuristik für technische Mängel; mit `--ki-fotos`
   bewertet zusätzlich Claude die Bilder wie ein Fotograf (Perspektive,
   stürzende Linien, Licht, Aufgeräumtheit, **Staging-Potenzial leerer Räume**)
   und liefert direkt ein Verkaufsargument.
4. **Instagram über die offizielle API, nicht per Scraping.** Das Handle wird
   von der Website gelesen. Die Aktivität (Follower, Posts, letzter Post,
   Engagement) liefert die Instagram Graph API „Business Discovery“ – dafür
   braucht die Agentur einen eigenen Instagram-Business-Account und ein
   Meta-App-Token. Ohne Token steht im Ergebnis „Aktivität manuell prüfen“.
5. **Scoring → Priorisierung → Pitch.** A-Leads (≥55 Punkte) zuerst anrufen.
   Ein guter Google-Schnitt (≥4,0 bei ≥20 Bewertungen) gibt einen Bonus: Der
   Betrieb läuft und hat vermutlich Budget.

### Punkte-Logik

| Befund | Punkte |
|---|---|
| Keine Website (Google-bestätigt / nur OSM) | 40 / 30 |
| Website nicht erreichbar | 35 |
| Website-Score < 50 / < 75 | 30 / 15 |
| Instagram inaktiv/eingeschlafen | 20 |
| Kein Instagram | 15 |
| Makler: schwache Fotos | 20 |
| Makler: kein 360° | 15 |
| Makler: kein Staging (hohes Potenzial laut KI / sonst) | 15 / 10 |
| Makler: keine Drohnenbilder | 5 |
| Google ≥4,0 bei ≥20 Bewertungen | +10 |

Die Werte stehen in `agentur_leads/scoring.py` und lassen sich leicht anpassen.

## Installation

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[ki,dev]"      # ohne KI-Fotobewertung reicht: pip install -e .
cp .env.example .env            # optionale Keys eintragen

# Zusätzlich für Verkaufsberichte (agentur-leads report):
pip install -e ".[report,ki]"   # Diagramme (matplotlib), Browser (Playwright), KI-Stichprobe
python -m playwright install chromium
npm install -g lighthouse@12    # lokale Lighthouse-Messung, entfällt mit PAGESPEED_API_KEY
```

## Benutzung

```bash
# Alles in einem Lauf: finden + prüfen
agentur-leads start --region "Münster" --radius 15

# Nur Makler, mit KI-Fotogutachten
agentur-leads start --region "Osnabrück" --segment makler --ki-fotos

# In zwei Schritten (leads.json vorher von Hand ausdünnen/ergänzen)
agentur-leads finden  --region "48143 Münster" --radius 10 --max 150
agentur-leads pruefen --leads output/leads.json
```

Ergebnisse in `output/`:

- `leads.csv` – für Excel (Semikolon, UTF-8), sortiert nach Priorität und Score
- `report.md` – Kurzüberblick und Top-25 mit Pitch
- `ergebnisse.json` – alle Details (z. B. jede einzelne Fotoanalyse)

Ein abgebrochener Lauf lässt sich einfach neu starten: Bereits geprüfte
Betriebe werden übersprungen.

### Optionale Schlüssel (`.env`)

| Variable | Wofür | Kosten |
|---|---|---|
| `GOOGLE_PLACES_API_KEY` | Vollständigere Betriebsliste + sichere Aussage „keine Website“ + Google-Bewertungen | Google Maps Platform, Freikontingent pro Monat |
| `IG_GRAPH_TOKEN`, `IG_BUSINESS_ACCOUNT_ID` | Instagram-Aktivität messen | kostenlos (Meta-App nötig) |
| `ANTHROPIC_API_KEY` | `--ki-fotos`: Foto-Gutachten durch Claude (bis 6 Bilder pro Makler); `report`: KI-Stichprobe | pro Anfrage, Anthropic API |
| `NOTION_TOKEN` | `report --notion` / `--veroeffentlichen`: Leads lesen, Berichte anlegen | kostenlos (interne Notion-Integration) |
| `PAGESPEED_API_KEY` | `report`: Lighthouse über Google statt lokal, inkl. Messwerten echter Besucher | kostenlos (Google Cloud) |
| `NOTION_LEADS_DATENQUELLE`, `AGENTUR_NAME`, `KI_SUCHE_MODELL` | `report`: Leads-Board, Absender im Bericht, Modell der KI-Stichprobe | – |

## Verkaufsberichte: Website-Check je Lead

`agentur-leads report` erstellt für jeden Lead einen ausführlichen Bericht mit
Diagrammen, Screenshots und Maßnahmenplan – als **PDF zum Vorlegen oder
Versenden**. Auf Wunsch hängt der Befehl das PDF direkt im Notion-Leads-Board an
(Spalte „Report-PDF“). Sechs Bereiche bekommen je 0–100 Punkte, daraus ergibt
sich die Gesamtnote:

| Bereich | Was gemessen wird |
|---|---|
| Ladezeit & Technik | Google Lighthouse am Handy (Median aus 3 Läufen) und am Computer: Ladezeit, Layout-Sprünge, Datenmenge |
| Kunden-Erlebnis | Vorschaltseiten, Kernfunktionen je Branche (Speisekarte/Reservierung, Terminbuchung, Objekte/Bewertung, Anfrageformular), antippbare Telefonnummer, kaputte Formulare (`[contact_form]`-Reste), Handy-Layout, Aktualität |
| Sicherheit & Datenschutz | HTTPS, unverschlüsselt eingebundene Dateien, Mozilla HTTP Observatory, PHP- und WordPress-Version, Impressum, Datenschutzerklärung, externe Dienste vor der Einwilligung (gemessen in einem echten Browser) |
| Google-Sichtbarkeit (SEO) | Titel, Beschreibungen, Überschriften, Alt-Texte, sprechende Adressen, eine eindeutige Adresse, Sitemap, robots.txt, Textmenge, Ort im Titel |
| KI-Auffindbarkeit | KI-Crawler in der robots.txt, Schema.org-Unternehmensdaten, llms.txt; mit `ANTHROPIC_API_KEY` eine Stichprobe: drei echte Fragen an Claude mit Websuche („Wer ist das beste vietnamesische Restaurant in Aachen?“) |
| Social Media & Content | Instagram, verlinkte Profile, Alter der Fotos, Google-Bewertungen im Vergleich zu anderen Leads gleicher Branche und Stadt |

Aus den nicht erfüllten Punkten entstehen Maßnahmen mit Aufwand und Wirkung,
gebündelt in drei Angebotspakete (Sofort-Fix, Neue Website, Sichtbarkeit &
Content). Dauer und Preis je Paket kommen aus einer kleinen JSON-Datei
(`--angebot angebot.json` oder `AGENTUR_ANGEBOT`):

```json
{"1": {"dauer": "1 Woche", "preis": "ab 390 €"},
 "2": {"dauer": "4–6 Wochen", "preis": "ab 2.900 €"},
 "3": {"dauer": "monatlich kündbar", "preis": "ab 290 € pro Monat"}}
```

Ohne Datei steht im PDF „Umfang, Dauer und Preis stimmen wir gern in einem
kurzen Gespräch auf Ihre Wünsche ab.“ `--kontakt` (oder `AGENTUR_KONTAKT`)
fügt am Ende einen Ansprechpartner ein.

```bash
# Einzelner Bericht, nur lokal → output/berichte/<name>/bericht.pdf (+ bericht.md, Diagramme)
agentur-leads report --url https://beispiel.de --name "Muster Bedachungen" \
  --branche Handwerk --kategorie Dachdecker --ort Aachen --rating 4.6 --bewertungen 38

# Alle Leads mit Website aus dem Notion-Board ansehen, ohne etwas in Notion zu schreiben
agentur-leads report --notion --trockenlauf --max 5

# Alle Leads: messen, PDF im Board anhängen (Report-PDF) und Report-Score/-Datum setzen
agentur-leads report --notion --veroeffentlichen

# zusätzlich je Lead eine Notion-Unterseite mit dem Bericht (Feld „Report“ verlinkt sie)
agentur-leads report --notion --veroeffentlichen --mit-seite
```

- **Notion-Zugang:** In Notion unter *Einstellungen → Verbindungen → Integrationen
  entwickeln* eine interne Integration anlegen (Inhalte lesen, aktualisieren,
  einfügen), sie im Board „📥 Leads“ über *••• → Verbindungen* hinzufügen und
  das Token als `NOTION_TOKEN` setzen. Die Report-Felder legt der Befehl beim
  ersten Veröffentlichen selbst an. Das PDF bleibt unter 5 MB (Grenze im
  Notion-Free-Plan); bei Bedarf werden die Screenshots stärker verkleinert.
- **Fortsetzbar:** Messungen liegen je Lead in `output/berichte/<name>/fakten.json`.
  Leads mit Report-Datum werden übersprungen, `--neu` misst neu. Die Übersicht
  aller Läufe steht in `output/berichte/uebersicht.csv`.
- **Ausgeschlossen** werden Leads mit Qualität „❌ Geschlossen“, „❓ Verdacht
  geschlossen“ oder „👻 Keine Online-Präsenz“.
- **Dauer:** ohne `PAGESPEED_API_KEY` rund 2–3 Minuten je Lead, vor allem wegen
  der lokalen Lighthouse-Läufe. Diese laufen immer nacheinander, weil parallele
  Chrome-Instanzen die Werte verfälschen. `--parallel 3` beschleunigt nur
  Crawling und Browser-Messung. `--schnell` misst am Handy erst einmal und stockt
  nur bei schwachen Werten (Leistung < 60) auf drei Messungen auf – für große
  Läufe etwa halb so lang. Mit `PAGESPEED_API_KEY` misst Google (parallel, ohne
  lokale Rechenlast), und der Bericht zeigt zusätzlich die Ladezeiten echter
  Besucher, sofern Google genug Daten hat.
- **Notion-Export als Quelle:** `--leads export.json` liest auch flache Board-Zeilen
  (Spalten wie im Board, dazu `url` der Seite), z. B. aus einem Export.
- **Ohne `NOTION_TOKEN`:** `scripts/gesamtlauf.py` erzeugt die Berichte für einen
  Board-Export nach Potenzial sortiert, `scripts/connector_upload.py` hilft beim
  Anhängen der PDFs über den Notion-Connector (Ablauf im Docstring).
- **KI-Stichprobe:** drei Fragen je Lead mit je bis zu zwei Websuchen. Die
  Websuche kostet 10 $ pro 1.000 Suchen, dazu kommen Tokens, grob 0,10–0,40 $
  je Lead mit dem Standardmodell (`KI_SUCHE_MODELL`, Standard `claude-opus-5-5`).
  Abschalten mit `--ohne-ki`.
- Der **Observatory-Scan** läuft über die öffentliche API von Mozilla (MDN). Wer
  das nicht möchte, nimmt `--ohne-observatory`.

## Rechtliches – bitte lesen

- **Daten:** Es werden nur öffentlich zugängliche Firmendaten verarbeitet.
  Auch Einzelunternehmer-Daten sind personenbezogen (DSGVO): Leads nur für
  diesen Zweck nutzen, nicht weitergeben, regelmäßig löschen, Herkunft auf
  Nachfrage nennen können (Art. 14 DSGVO).
- **Kontaktaufnahme (UWG § 7):** Kalt-E-Mails an Unternehmen ohne
  Einwilligung sind in Deutschland unzulässig. Telefon ist bei Gewerbetreibenden
  nur bei *mutmaßlicher* Einwilligung erlaubt (konkreter Bezug zum Betrieb).
  Sicherer Weg: Brief/Postkarte mit dem konkreten Befund („Ihre Website ist auf
  dem Handy nicht lesbar“) oder persönlich vorbeigehen.
- **Plattformen:** Instagram wird nur über die offizielle API abgefragt;
  Immobilienportale werden nicht gescrapt.

## Entwicklung

```bash
pytest
```

Die Tests laufen komplett offline mit HTML-Fixtures und generierten Testbildern.

```
agentur_leads/
  discovery/osm.py, google_places.py   Betriebe finden
  audit/website.py                     Website-Check + Social-Links
  audit/makler.py, fotos.py            Objektseiten, 360°, Staging, Fotoqualität
  audit/ki_bewertung.py                optionales Claude-Fotogutachten
  audit/instagram.py                   Handle + Aktivität (Graph API)
  scoring.py                           Chancen, Score, Priorität, Pitch
  pipeline.py, export.py, cli.py
```

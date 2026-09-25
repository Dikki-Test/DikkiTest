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
| `ANTHROPIC_API_KEY` | `--ki-fotos`: Foto-Gutachten durch Claude (bis 6 Bilder pro Makler) | pro Anfrage, Anthropic API |

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

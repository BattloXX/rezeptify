"""Claude AI client, prompts (with metric conversion) and robust JSON parser."""
import json, re
from typing import Optional

from anthropic import Anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

_claude: Optional[Anthropic] = None


def get_claude() -> Anthropic:
    global _claude
    if _claude is None:
        _claude = Anthropic(api_key=ANTHROPIC_API_KEY)
    return _claude


def check_api_key():
    from fastapi import HTTPException
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("sk-ant-DEIN"):
        raise HTTPException(500, "ANTHROPIC_API_KEY nicht konfiguriert")


# ── JSON Schema & Rules ────────────────────────────────────────────────────────

_JSON_SCHEMA = """{
  "titel": "Rezeptname",
  "beschreibung": "Kurzbeschreibung (1-2 Sätze)",
  "zutaten": [
    {"gruppe": "Für den Teig"},
    {"menge": "200", "einheit": "g", "name": "Mehl"},
    {"menge": "3", "einheit": "EL", "name": "Olivenöl"},
    {"gruppe": "Für die Sauce"},
    {"menge": "", "einheit": "", "name": "Salz nach Geschmack"}
  ],
  "zubereitung": "Schritt-für-Schritt Zubereitung",
  "portionen": 4,
  "zeit_vorb": 15,
  "zeit_koch": 30,
  "schwierigkeit": "leicht",
  "kategorie": "Hauptgericht",
  "tags": ["vegetarisch", "schnell"],
  "kalorien_pro_portion": 450
}"""

_METRIC_RULES = """
Metrische Einheiten-Konvertierung (PFLICHT — immer anwenden):
- ALLE nicht-metrischen Einheiten MÜSSEN umgerechnet werden
- Flüssigkeiten: 1 cup = 240 ml | 1/2 cup = 120 ml | 1/4 cup = 60 ml | 1 fl oz = 30 ml
- Trockene Zutaten (Volumen → Gewicht): 1 cup Mehl = 120 g | 1 cup Zucker = 200 g | 1 cup Butter = 227 g | 1 cup Haferflocken = 90 g | 1 cup Nüsse = 120 g | 1 cup Reis (roh) = 185 g
- Löffel: EL (Esslöffel/tablespoon/tbsp) = 15 ml BLEIBEN als "EL" | TL (Teelöffel/teaspoon/tsp) = 5 ml BLEIBEN als "TL"
- Gewicht: 1 oz = 28 g (runden auf 30 g) | 1 lb = 454 g (runden auf 450 g) | 1 stick Butter = 113 g (runden auf 115 g)
- Temperatur in Zubereitung: °F → °C: (°F − 32) × 5/9, auf 5 °C runden (350 °F = 175 °C | 375 °F = 190 °C | 400 °F = 200 °C | 425 °F = 220 °C)
- Mengen sinnvoll runden: 113 g → 115 g | 227 g → 225 g | 454 g → 450 g | 240 ml bleibt 240 ml
- Erlaubte Einheiten: g, kg, ml, l, EL, TL, Prise, Stück, Scheibe, Zweig, Blatt, nach Geschmack
- VERBOTEN: cups, cup, oz, lbs, lb, sticks, stick, °F, fl oz"""

_GENERAL_RULES = """
Allgemeine Regeln:
- Antworte NUR mit dem JSON-Objekt – KEIN Markdown, KEINE Backticks, KEIN Text davor oder danach
- Alle Strings müssen gültige JSON-Strings sein (keine unescapten Anführungszeichen darin)
- Zeilenumbrüche in Strings als \\n schreiben, nicht als echte Zeilenumbrüche
- schwierigkeit: nur "leicht", "mittel" oder "schwer"
- kategorie: Frühstück | Vorspeise | Hauptgericht | Dessert | Snack | Getränk | Backen | Salat | Suppe | Sonstiges
- zeit_vorb / zeit_koch: Minuten als Ganzzahl (0 wenn unbekannt)
- kalorien_pro_portion: Geschätzte kcal pro Portion als Ganzzahl. Anhand der (konvertierten) Zutaten berechnen. Falls nicht schätzbar: null
- zutaten: Falls Gruppen vorhanden, {"gruppe": "Gruppenname"} als Marker vor der Gruppe einfügen
- Falls kein Rezept erkennbar: {"fehler": "Kein Rezept gefunden"}
- Antworte auf Deutsch"""

PROMPT_URL = (
    f"Du bist ein Rezept-Extraktor. Analysiere den Webseiteninhalt und extrahiere das Rezept.\n\n"
    f"Gib dieses JSON zurück:\n{_JSON_SCHEMA}\n\n{_METRIC_RULES}\n\n{_GENERAL_RULES}\n\nInhalt:"
)

PROMPT_IMAGE = (
    f"Du bist ein Rezept-Extraktor. Analysiere das Bild/PDF (Screenshot, Foto oder PDF eines Rezepts).\n\n"
    f"Gib dieses JSON zurück:\n{_JSON_SCHEMA}\n\n{_METRIC_RULES}\n\n{_GENERAL_RULES}"
)

SEARCH_SYSTEM = """Du bist ein Rezept-Assistent für die Familie Battlogg in Vorarlberg, Österreich.

Deine Aufgabe: Suche 2-3 der besten Rezepte im Internet basierend auf dem Wunsch des Benutzers.

Wichtige Kriterien:
- Nur Rezepte mit guten Bewertungen (mindestens 4 Sterne oder sehr positiven Kommentaren)
- Bevorzuge deutschsprachige Quellen: chefkoch.de, lecker.de, küchengötter.de, gutekueche.at, ichkoche.at, rezeptwelt.at
- Ernährungseinschränkungen und Wünsche des Benutzers beachten
- Zutaten im deutschsprachigen Raum erhältlich (keine exotischen US-Spezialitäten)

""" + _METRIC_RULES + """

Ablauf:
1. Suche im Web nach passenden Rezepten
2. Wähle die 2-3 besten basierend auf Bewertungen und Relevanz
3. Extrahiere jedes Rezept vollständig mit metrischen Einheiten
4. Antworte NUR mit einem validen JSON-Array (kein Markdown, keine Erklärungen):

[
  {
    "titel": "Rezeptname",
    "beschreibung": "Kurzbeschreibung (1-2 Sätze)",
    "zutaten": [
      {"gruppe": "Für den Teig"},
      {"menge": "200", "einheit": "g", "name": "Mehl"},
      {"menge": "3", "einheit": "EL", "name": "Olivenöl"}
    ],
    "zubereitung": "Schritt-für-Schritt Zubereitung",
    "portionen": 4,
    "zeit_vorb": 15,
    "zeit_koch": 30,
    "schwierigkeit": "leicht",
    "kategorie": "Hauptgericht",
    "tags": ["vegetarisch", "schnell"],
    "kalorien_pro_portion": 450,
    "quelle_url": "https://...",
    "quelle_typ": "web",
    "suchinfo": "Bewertung und Quelle, z.B. '4.8 Sterne auf Chefkoch, über 500 Bewertungen'"
  }
]

Regeln:
- Antworte AUSSCHLIESSLICH mit dem JSON-Array — KEIN Text davor oder danach, KEINE Markdown-Backticks
- Deine gesamte Antwort muss mit [ beginnen und mit ] enden
- Gib IMMER ein Array zurück, auch wenn nur 1 Ergebnis vorhanden
- schwierigkeit: nur "leicht", "mittel" oder "schwer"
- kategorie: Frühstück | Vorspeise | Hauptgericht | Dessert | Snack | Getränk | Backen | Salat | Suppe | Sonstiges
- Antworte auf Deutsch
- Falls kein passendes Rezept: [{"fehler": "Kein passendes Rezept gefunden: [Grund]"}]"""


def clean_html(html: str) -> str:
    from bs4 import BeautifulSoup
    try:
        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside',
                         'iframe', 'noscript', 'form', 'button', 'svg', 'meta', 'link']):
            tag.decompose()
        main = (
            soup.find('main') or
            soup.find(id='recipe') or
            soup.find(id='wprm-recipe-container') or
            soup.find(class_='wprm-recipe-container') or
            soup.find(class_='tasty-recipes') or
            soup.find(class_='recipe-card') or
            soup.find(class_='recipe') or
            soup.find(attrs={'itemtype': 'http://schema.org/Recipe'}) or
            soup.find('article') or
            soup
        )
        text = ' '.join(main.get_text(separator=' ', strip=True).split())
        return text[:15000]
    except Exception:
        text = re.sub(r'<[^>]+>', ' ', html)
        return ' '.join(text.split())[:15000]


def parse_claude(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'^```\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    truncated = raw.rstrip().rstrip(',')
    for suffix in ['"}', '"]}', '"}]}', '"\n}', ']\n}']:
        try:
            return json.loads(truncated + '\n' + suffix)
        except json.JSONDecodeError:
            pass
    fixed = re.sub(r"(?<![\\])'", '"', raw)
    fixed = re.sub(r',\s*([}\]])', r'\1', fixed)
    fixed = re.sub(r'[\x00-\x1f\x7f]', ' ', fixed)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass
    raise ValueError(f"JSON konnte nicht geparst werden. Antwort: {raw[:300]}")

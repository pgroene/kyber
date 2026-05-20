"""Language-specific vocabulary hints for Kyber.

These hints are seeded into the knowledge store at startup
(category "language_hint") and injected automatically into the AI context
when the user's message is detected as non-English.  The system prompt stays
fully generic; all locale-specific content lives here.

Adding a new language: add one entry to ``LANGUAGE_HINTS``.
Bump ``LANG_HINTS_VERSION`` whenever you change existing hint content so the
store re-seeds automatically on the next HA restart.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# Bump when hint content changes — triggers automatic re-seed on next startup.
LANG_HINTS_VERSION = 3

_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", re.UNICODE)


class LangHintEntry(NamedTuple):
    subject: str
    content: str


# Each language entry contains:
#   name     – English display name
#   markers  – high-frequency words unique to this language (used for detection)
#   hints    – list of LangHintEntry facts to seed into the knowledge store
LANGUAGE_HINTS: dict[str, dict] = {
    "nl": {
        "name": "Dutch",
        "markers": {
            "de", "het", "een", "aan", "uit", "doen", "zet", "doe",
            "maak", "kan", "wil", "naar", "ook", "niet", "ik", "je", "mij",
        },
        "hints": [
            LangHintEntry(
                "nl_actions",
                "Dutch home-automation action phrases: "
                "'aan doen' / 'aanzetten' / 'zet aan' / 'doe aan' / 'inschakelen' = turn on. "
                "'uit doen' / 'uitzetten' / 'zet uit' / 'doe uit' / 'uitschakelen' = turn off. "
                "'omschakelen' / 'toggle' = toggle.",
            ),
            LangHintEntry(
                "nl_brightness",
                "Dutch brightness words: "
                "'maximaal' / 'vol' / 'volledig' / 'zo fel mogelijk' / 'helemaal aan' = max brightness (100%). "
                "'gedimd' / 'zwak' / 'minimaal' / 'zo laag mogelijk' = dim (10%). "
                "'helderder' / 'feller' = brighter. 'donkerder' / 'dimmer' = dimmer.",
            ),
            LangHintEntry(
                "nl_rooms",
                "Dutch area/room words: "
                "woonkamer = living room, slaapkamer = bedroom, werkkamer/kantoor = office/study, "
                "keuken = kitchen, badkamer = bathroom, hal/gang = hallway, "
                "tuin = garden, zolder = attic, kelder = basement, "
                "eetkamer = dining room, garage = garage.",
            ),
            LangHintEntry(
                "nl_devices",
                "Dutch device words: "
                "lamp/licht/verlichting = light, televisie/tv/scherm = media_player TV, "
                "muziek/speaker/geluid = music/media, verwarming = heating/climate, "
                "thermostaat = thermostat, gordijnen/jaloezieen/rolluik = curtains/cover/shutter, "
                "ventilator/airco = fan/AC. "
                "Kitchen appliances: "
                "koffiezetapparaat/koffiemachine/koffiezet = coffee maker/espresso machine, "
                "espressomachine/espresso apparaat = espresso machine, "
                "vaatwasser/afwasmachine = dishwasher, "
                "wasmachine = washing machine, "
                "droger/droogkast = dryer, "
                "oven/magnetron = oven/microwave, "
                "koelkast = refrigerator/fridge, "
                "vriezer = freezer, "
                "waterkoker = kettle, "
                "broodrooster = toaster, "
                "afzuigkap = extractor hood.",
            ),
            LangHintEntry(
                "nl_confirmation",
                "Dutch confirmation phrases: "
                "'ja' / 'oké' / 'prima' / 'goed' / 'doe dat' / 'voer uit' = yes/confirm. "
                "'nee' / 'stop' = no/cancel.",
            ),
        ],
    },
    "de": {
        "name": "German",
        "markers": {
            "das", "die", "der", "ein", "eine", "ist", "und", "ich",
            "bitte", "mach", "schalte", "kannst", "nicht", "auch", "mir",
        },
        "hints": [
            LangHintEntry(
                "de_actions",
                "German home-automation action phrases: "
                "'einschalten' / 'anmachen' / 'anschalten' = turn on. "
                "'ausschalten' / 'ausmachen' = turn off. "
                "'umschalten' = toggle.",
            ),
            LangHintEntry(
                "de_brightness",
                "German brightness words: "
                "'maximale Helligkeit' / 'ganz hell' / 'voll aufdrehen' = max brightness (100%). "
                "'gedimmt' / 'dunkel' / 'minimale Helligkeit' = dim (10%). "
                "'heller' = brighter. 'dunkler' / 'dimmer' = dimmer.",
            ),
            LangHintEntry(
                "de_rooms",
                "German area/room words: "
                "Wohnzimmer = living room, Schlafzimmer = bedroom, Küche = kitchen, "
                "Badezimmer/Bad = bathroom, Flur/Gang = hallway, Garten = garden, "
                "Büro/Arbeitszimmer = office, Keller = basement, "
                "Esszimmer = dining room, Garage = garage.",
            ),
            LangHintEntry(
                "de_devices",
                "German device words: "
                "Lampe/Licht/Beleuchtung = light, Fernseher/TV = media_player TV, "
                "Musik/Lautsprecher = music/media, Heizung = heating/climate, "
                "Thermostat = thermostat, Jalousien/Rollladen = blinds/cover, "
                "Ventilator/Klimaanlage = fan/AC. "
                "Kitchen appliances: "
                "Kaffeemaschine/Kaffeeautomat/Espressomaschine = coffee maker/espresso machine, "
                "Geschirrspüler/Spülmaschine = dishwasher, "
                "Waschmaschine = washing machine, "
                "Trockner = dryer, "
                "Backofen/Mikrowelle = oven/microwave, "
                "Kühlschrank = refrigerator/fridge, "
                "Gefrierschrank/Tiefkühler = freezer, "
                "Wasserkocher = kettle, "
                "Toaster = toaster, "
                "Dunstabzugshaube = extractor hood.",
            ),
        ],
    },
    "fr": {
        "name": "French",
        "markers": {
            "le", "la", "les", "un", "une", "est", "je", "tu",
            "allume", "eteins", "mets", "peux", "dans", "aussi", "moi",
        },
        "hints": [
            LangHintEntry(
                "fr_actions",
                "French home-automation action phrases: "
                "'allume' / 'allumer' / 'activer' = turn on. "
                "'éteins' / 'éteindre' / 'désactiver' = turn off. "
                "'basculer' = toggle.",
            ),
            LangHintEntry(
                "fr_brightness",
                "French brightness words: "
                "'luminosité maximale' / 'pleine lumière' = max brightness (100%). "
                "'tamisé' / 'luminosité minimale' = dim (10%). "
                "'plus lumineux' = brighter. 'plus sombre' / 'tamiser' = dimmer.",
            ),
            LangHintEntry(
                "fr_rooms",
                "French area/room words: "
                "salon/salle de séjour = living room, chambre = bedroom, "
                "cuisine = kitchen, salle de bain = bathroom, couloir/entrée = hallway, "
                "jardin = garden, bureau = office, cave = basement, "
                "salle à manger = dining room.",
            ),
            LangHintEntry(
                "fr_devices",
                "French device words: "
                "lampe/lumière/éclairage = light, télé/téléviseur = media_player TV, "
                "musique/enceinte = music/media, chauffage = heating/climate, "
                "thermostat = thermostat, volets/stores = curtains/cover, "
                "ventilateur/climatiseur = fan/AC. "
                "Kitchen appliances: "
                "cafetière/machine à café/machine à expresso = coffee maker/espresso machine, "
                "lave-vaisselle = dishwasher, "
                "machine à laver/lave-linge = washing machine, "
                "sèche-linge = dryer, "
                "four/micro-ondes = oven/microwave, "
                "réfrigérateur/frigo = refrigerator/fridge, "
                "congélateur = freezer, "
                "bouilloire = kettle, "
                "grille-pain = toaster, "
                "hotte aspirante = extractor hood.",
            ),
        ],
    },
    "es": {
        "name": "Spanish",
        "markers": {
            "el", "la", "los", "las", "un", "una", "es", "yo",
            "enciende", "apaga", "pon", "puedes", "también", "no", "me",
        },
        "hints": [
            LangHintEntry(
                "es_actions",
                "Spanish home-automation action phrases: "
                "'enciende' / 'encender' / 'activar' = turn on. "
                "'apaga' / 'apagar' / 'desactivar' = turn off. "
                "'alternar' = toggle.",
            ),
            LangHintEntry(
                "es_brightness",
                "Spanish brightness words: "
                "'brillo máximo' / 'al máximo' = max brightness (100%). "
                "'tenue' / 'brillo mínimo' = dim (10%). "
                "'más brillante' = brighter. 'más oscuro' / 'atenuar' = dimmer.",
            ),
            LangHintEntry(
                "es_rooms",
                "Spanish area/room words: "
                "sala/salón = living room, dormitorio/habitación = bedroom, "
                "cocina = kitchen, baño = bathroom, pasillo = hallway, "
                "jardín = garden, oficina/despacho = office, "
                "garaje = garage, comedor = dining room.",
            ),
            LangHintEntry(
                "es_devices",
                "Spanish device words: "
                "lámpara/luz = light, televisor/TV = media_player TV, "
                "música/altavoz = music/media, calefacción = heating/climate, "
                "termostato = thermostat, persianas/cortinas = curtains/cover, "
                "ventilador/AC = fan/AC. "
                "Kitchen appliances: "
                "cafetera/máquina de café/máquina de espresso = coffee maker/espresso machine, "
                "lavavajillas = dishwasher, "
                "lavadora = washing machine, "
                "secadora = dryer, "
                "horno/microondas = oven/microwave, "
                "frigorífico/nevera = refrigerator/fridge, "
                "congelador = freezer, "
                "hervidor = kettle, "
                "tostadora = toaster, "
                "campana extractora = extractor hood.",
            ),
        ],
    },
    "it": {
        "name": "Italian",
        "markers": {
            "il", "la", "lo", "un", "una", "è", "io", "accendi",
            "spegni", "puoi", "anche", "non", "della", "mi",
        },
        "hints": [
            LangHintEntry(
                "it_actions",
                "Italian home-automation action phrases: "
                "'accendi' / 'accendere' / 'attivare' = turn on. "
                "'spegni' / 'spegnere' / 'disattivare' = turn off. "
                "'alternare' = toggle.",
            ),
            LangHintEntry(
                "it_brightness",
                "Italian brightness words: "
                "'luminosità massima' / 'al massimo' = max brightness (100%). "
                "'fioca' / 'luminosità minima' = dim (10%). "
                "'più luminoso' = brighter. 'più scuro' / 'attenuare' = dimmer.",
            ),
            LangHintEntry(
                "it_rooms",
                "Italian area/room words: "
                "soggiorno = living room, camera/camera da letto = bedroom, "
                "cucina = kitchen, bagno = bathroom, corridoio = hallway, "
                "giardino = garden, ufficio/studio = office, garage = garage.",
            ),
            LangHintEntry(
                "it_devices",
                "Italian device words: "
                "lampada/luce = light, televisore/TV = media_player TV, "
                "musica/altoparlante = music/media, riscaldamento = heating/climate, "
                "termostato = thermostat, persiane/tende = curtains/cover, "
                "ventilatore/climatizzatore = fan/AC. "
                "Kitchen appliances: "
                "macchina del caffè/caffettiera/macchina per espresso = coffee maker/espresso machine, "
                "lavastoviglie = dishwasher, "
                "lavatrice = washing machine, "
                "asciugatrice = dryer, "
                "forno/microonde = oven/microwave, "
                "frigorifero/frigo = refrigerator/fridge, "
                "congelatore = freezer, "
                "bollitore = kettle, "
                "tostapane = toaster, "
                "cappa aspirante = extractor hood.",
            ),
        ],
    },
    "pt": {
        "name": "Portuguese",
        "markers": {
            "o", "a", "os", "as", "um", "uma", "é", "eu",
            "liga", "desliga", "pode", "também", "não", "me", "aqui",
        },
        "hints": [
            LangHintEntry(
                "pt_actions",
                "Portuguese home-automation action phrases: "
                "'liga' / 'ligar' / 'ativar' = turn on. "
                "'desliga' / 'desligar' / 'desativar' = turn off. "
                "'alternar' = toggle.",
            ),
            LangHintEntry(
                "pt_brightness",
                "Portuguese brightness words: "
                "'brilho máximo' / 'no máximo' = max brightness (100%). "
                "'ténue' / 'brilho mínimo' = dim (10%). "
                "'mais brilhante' = brighter. 'mais escuro' / 'reduzir' = dimmer.",
            ),
            LangHintEntry(
                "pt_rooms",
                "Portuguese area/room words: "
                "sala/sala de estar = living room, quarto = bedroom, "
                "cozinha = kitchen, banheiro/casa de banho = bathroom, "
                "corredor = hallway, jardim = garden, escritório = office.",
            ),
            LangHintEntry(
                "pt_devices",
                "Portuguese device words: "
                "lâmpada/luz = light, televisor/TV = media_player TV, "
                "música/alto-falante = music/media, aquecimento = heating/climate, "
                "termostato = thermostat, persianas/cortinas = curtains/cover. "
                "Kitchen appliances: "
                "máquina de café/cafeteira/máquina de espresso = coffee maker/espresso machine, "
                "máquina de lavar louça/lava-louças = dishwasher, "
                "máquina de lavar/máquina de lavar roupa = washing machine, "
                "secadora = dryer, "
                "forno/micro-ondas = oven/microwave, "
                "frigorífico/geladeira = refrigerator/fridge, "
                "congelador = freezer, "
                "chaleira = kettle, "
                "torradeira = toaster, "
                "exaustor = extractor hood.",
            ),
        ],
    },
}


def detect_language(text: str) -> str:
    """Detect the primary language of *text* using marker-word frequency.

    Returns a BCP-47 primary sub-tag (e.g. ``"nl"``, ``"de"``) or ``"en"``
    when no non-English language is detected confidently enough.

    Detection is intentionally lightweight (no external deps): it counts how
    many high-frequency, language-unique marker words appear in the token set.
    A language wins when ≥2 of its markers are present AND it has the most
    marker hits of all candidates.
    """
    if not text:
        return "en"
    tokens = {w.lower() for w in _TOKEN_RE.findall(text)}
    scores: dict[str, int] = {}
    for code, lang in LANGUAGE_HINTS.items():
        hits = len(tokens & lang["markers"])
        if hits >= 2:
            scores[code] = hits
    if not scores:
        return "en"
    return max(scores, key=lambda c: scores[c])


def get_hints_for_language(lang_code: str) -> list[LangHintEntry]:
    """Return the hint entries for *lang_code*, or ``[]`` for English/unknown."""
    lang = LANGUAGE_HINTS.get(lang_code)
    return list(lang["hints"]) if lang else []


def language_display_name(lang_code: str) -> str:
    """Return the English display name for a language code."""
    lang = LANGUAGE_HINTS.get(lang_code)
    return lang["name"] if lang else lang_code


# Static map: native appliance word (any language) → English search term(s).
# Used for knowledge retrieval before AI query expansion so the model cannot
# accidentally conflate appliances via shared brand names (e.g. "miele" matches
# both washing machine and dishwasher).
_APPLIANCE_TRANSLATIONS: dict[str, list[str]] = {
    # Dutch
    "afwasmachine": ["dishwasher"],
    "vaatwasser": ["dishwasher"],
    "wasmachine": ["washing machine"],
    "droger": ["dryer"],
    "droogkast": ["dryer"],
    "magnetron": ["microwave"],
    "koelkast": ["refrigerator", "fridge"],
    "vriezer": ["freezer"],
    "waterkoker": ["kettle"],
    "broodrooster": ["toaster"],
    "afzuigkap": ["extractor hood"],
    "koffiezetapparaat": ["coffee maker"],
    "koffiemachine": ["coffee maker"],
    "espressomachine": ["espresso machine"],
    # German
    "geschirrspüler": ["dishwasher"],
    "spülmaschine": ["dishwasher"],
    "waschmaschine": ["washing machine"],
    "trockner": ["dryer"],
    "backofen": ["oven"],
    "mikrowelle": ["microwave"],
    "kühlschrank": ["refrigerator", "fridge"],
    "gefrierschrank": ["freezer"],
    "wasserkocher": ["kettle"],
    "kaffeemaschine": ["coffee maker"],
    "espressomaschine": ["espresso machine"],
    # French
    "lave-vaisselle": ["dishwasher"],
    "lave-linge": ["washing machine"],
    "sèche-linge": ["dryer"],
    "réfrigérateur": ["refrigerator", "fridge"],
    "congélateur": ["freezer"],
    "bouilloire": ["kettle"],
    "grille-pain": ["toaster"],
    "cafetière": ["coffee maker"],
    # Spanish
    "lavavajillas": ["dishwasher"],
    "lavadora": ["washing machine"],
    "secadora": ["dryer"],
    "frigorífico": ["refrigerator", "fridge"],
    "congelador": ["freezer"],
    "hervidor": ["kettle"],
    "tostadora": ["toaster"],
    # Italian
    "lavastoviglie": ["dishwasher"],
    "lavatrice": ["washing machine"],
    "asciugatrice": ["dryer"],
    "frigorifero": ["refrigerator", "fridge"],
    "congelatore": ["freezer"],
    "bollitore": ["kettle"],
    "tostapane": ["toaster"],
    "lavastoviglie": ["dishwasher"],
    # Portuguese
    "lava-louças": ["dishwasher"],
    "máquina de lavar": ["washing machine"],
    "secadora": ["dryer"],
    "frigorífico": ["refrigerator", "fridge"],
    "congelador": ["freezer"],
    "chaleira": ["kettle"],
    "torradeira": ["toaster"],
}


def get_appliance_translations(text: str) -> list[str]:
    """Return English appliance terms for any native-language appliance words in *text*.

    Runs a simple substring scan against the static map — no AI call needed.
    Returns an empty list when nothing matches.
    """
    lower = text.lower()
    found: list[str] = []
    for word, english_terms in _APPLIANCE_TRANSLATIONS.items():
        if word in lower:
            found.extend(t for t in english_terms if t not in found)
    return found


# ── Static word-level translator ─────────────────────────────────────────────
# Maps individual home-automation words (rooms, devices, actions) from each
# supported language to their English equivalents.  Used to translate user
# queries to English before TF-IDF knowledge retrieval, since the knowledge
# store is indexed over English text.
#
# Multi-word appliance terms are handled separately by _APPLIANCE_TRANSLATIONS
# (applied first as substring replacements before word-level substitution).

_WORD_TRANSLATIONS: dict[str, str] = {
    # ── Dutch (nl) ───────────────────────────────────────────────────────────
    # Rooms
    "woonkamer": "living room",
    "slaapkamer": "bedroom",
    "werkkamer": "office",
    "kantoor": "office",
    "keuken": "kitchen",
    "badkamer": "bathroom",
    "hal": "hallway",
    "gang": "hallway",
    "tuin": "garden",
    "zolder": "attic",
    "kelder": "basement",
    "eetkamer": "dining room",
    "garage": "garage",
    # Devices
    "lamp": "light",
    "licht": "light",
    "verlichting": "lighting",
    "televisie": "television",
    "muziek": "music",
    "speaker": "speaker",
    "geluid": "sound",
    "verwarming": "heating",
    "thermostaat": "thermostat",
    "gordijnen": "curtains",
    "jaloezieen": "blinds",
    "rolluik": "shutter",
    "ventilator": "fan",
    "airco": "ac",
    # Actions
    "aanzetten": "turn on",
    "uitzetten": "turn off",
    "inschakelen": "turn on",
    "uitschakelen": "turn off",
    "starten": "start",
    "stoppen": "stop",
    "pauzeren": "pause",
    "hervatten": "resume",
    "instellen": "set",
    "aanpassen": "adjust",
    "verhoog": "increase",
    "verlaag": "decrease",
    "helderder": "brighter",
    "donkerder": "dimmer",
    "maximaal": "maximum",
    "minimaal": "minimum",
    # ── German (de) ──────────────────────────────────────────────────────────
    # Rooms
    "wohnzimmer": "living room",
    "schlafzimmer": "bedroom",
    "küche": "kitchen",
    "badezimmer": "bathroom",
    "flur": "hallway",
    "garten": "garden",
    "büro": "office",
    "arbeitszimmer": "office",
    "esszimmer": "dining room",
    "keller": "basement",
    # Devices
    "lampe": "light",
    "licht": "light",
    "fernseher": "television",
    "musik": "music",
    "lautsprecher": "speaker",
    "heizung": "heating",
    "thermostat": "thermostat",
    "jalousien": "blinds",
    "rollladen": "shutter",
    "klimaanlage": "ac",
    # Actions
    "einschalten": "turn on",
    "ausschalten": "turn off",
    "anmachen": "turn on",
    "ausmachen": "turn off",
    "starten": "start",
    "stoppen": "stop",
    "einstellen": "set",
    "heller": "brighter",
    "dunkler": "dimmer",
    # ── French (fr) ──────────────────────────────────────────────────────────
    # Rooms
    "salon": "living room",
    "chambre": "bedroom",
    "cuisine": "kitchen",
    "couloir": "hallway",
    "jardin": "garden",
    "bureau": "office",
    "cave": "basement",
    # Devices
    "lumière": "light",
    "lampe": "light",
    "télé": "television",
    "musique": "music",
    "chauffage": "heating",
    "volets": "shutters",
    "stores": "blinds",
    "climatiseur": "ac",
    # Actions
    "allumer": "turn on",
    "éteindre": "turn off",
    "démarrer": "start",
    "arrêter": "stop",
    "régler": "set",
    # ── Spanish (es) ─────────────────────────────────────────────────────────
    # Rooms
    "salón": "living room",
    "dormitorio": "bedroom",
    "cocina": "kitchen",
    "baño": "bathroom",
    "pasillo": "hallway",
    "jardín": "garden",
    "oficina": "office",
    "comedor": "dining room",
    "garaje": "garage",
    # Devices
    "luz": "light",
    "lámpara": "light",
    "televisor": "television",
    "música": "music",
    "calefacción": "heating",
    "persianas": "blinds",
    "cortinas": "curtains",
    # Actions
    "encender": "turn on",
    "apagar": "turn off",
    "iniciar": "start",
    "detener": "stop",
    "ajustar": "adjust",
    # ── Italian (it) ─────────────────────────────────────────────────────────
    # Rooms
    "soggiorno": "living room",
    "camera": "bedroom",
    "cucina": "kitchen",
    "bagno": "bathroom",
    "corridoio": "hallway",
    "giardino": "garden",
    "ufficio": "office",
    # Devices
    "luce": "light",
    "lampada": "light",
    "televisore": "television",
    "musica": "music",
    "riscaldamento": "heating",
    "persiane": "blinds",
    "tende": "curtains",
    # Actions
    "accendere": "turn on",
    "spegnere": "turn off",
    "avviare": "start",
    "fermare": "stop",
    "regolare": "set",
}


def translate_query_to_english(text: str) -> str:
    """Translate a user query to English for TF-IDF knowledge retrieval.

    Applies multi-word appliance substitutions first, then word-by-word
    substitution for rooms/devices/actions.  Unknown words are kept as-is
    (entity names and proper nouns are typically language-neutral).
    """
    result = text.lower()
    # Step 1: multi-word appliance terms (e.g. "afwasmachine" → "dishwasher")
    for native, english_terms in _APPLIANCE_TRANSLATIONS.items():
        if native in result:
            result = result.replace(native, english_terms[0])
    # Step 2: word-by-word substitution
    words = result.split()
    result = " ".join(_WORD_TRANSLATIONS.get(w, w) for w in words)
    return result.strip()

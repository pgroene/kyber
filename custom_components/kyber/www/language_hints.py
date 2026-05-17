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
LANG_HINTS_VERSION = 1

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
                "ventilator/airco = fan/AC.",
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
                "Ventilator/Klimaanlage = fan/AC.",
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
                "ventilateur/climatiseur = fan/AC.",
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
                "ventilador/AC = fan/AC.",
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
                "ventilatore/climatizzatore = fan/AC.",
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
                "termostato = thermostat, persianas/cortinas = curtains/cover.",
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

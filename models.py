from pydantic import BaseModel
from typing import Optional, List


class Zutat(BaseModel):
    menge:   Optional[str] = ""
    einheit: Optional[str] = ""
    name:    Optional[str] = ""
    gruppe:  Optional[str] = None


class RezeptIn(BaseModel):
    titel:                   str
    beschreibung:            Optional[str] = ""
    zutaten:                 Optional[List[Zutat]] = []
    zubereitung:             Optional[str] = ""
    portionen:               Optional[int] = 4
    zeit_vorb:               Optional[int] = 0
    zeit_koch:               Optional[int] = 0
    schwierigkeit:           Optional[str] = "mittel"
    kategorie:               Optional[str] = ""
    tags:                    Optional[List[str]] = []
    quelle_url:              Optional[str] = ""
    quelle_typ:              Optional[str] = "manuell"
    quelldatei:              Optional[str] = None
    kalorien_pro_portion:    Optional[int] = None

import re, unicodedata


def make_slug(titel: str, rid: int = None) -> str:
    s = titel.lower().strip()
    for src, dst in [('ä','ae'),('ö','oe'),('ü','ue'),('ß','ss'),
                     ('à','a'),('á','a'),('â','a'),('è','e'),('é','e'),
                     ('ê','e'),('ì','i'),('í','i'),('î','i'),('ò','o'),
                     ('ó','o'),('ô','o'),('ù','u'),('ú','u'),('û','u')]:
        s = s.replace(src, dst)
    s = unicodedata.normalize('NFD', s).encode('ascii', 'ignore').decode('ascii')
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    if len(s) > 80:
        s = s[:80].rstrip('-')
    if rid:
        s = f"{s}-{rid}"
    return s or f"rezept-{rid}"

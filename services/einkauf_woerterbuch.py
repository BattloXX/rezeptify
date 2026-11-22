"""Starter vocabulary; INSERT IGNORE preserves every learned assignment."""
from services.shopping_service import normalize_name

KATEGORIEN = [
    ('Obst & Gemüse', 'nutrition'), ('Brot & Backwaren', 'bakery_dining'),
    ('Kühlregal & Milch', 'egg'), ('Käse & Wurst', 'lunch_dining'),
    ('Fleisch & Fisch', 'set_meal'), ('Tiefkühl', 'ac_unit'),
    ('Nudeln, Reis & Trockenwaren', 'rice_bowl'), ('Konserven & Saucen', 'soup_kitchen'),
    ('Backen & Gewürze', 'cookie'), ('Frühstück & Süßes', 'breakfast_dining'),
    ('Getränke', 'local_drink'), ('Drogerie', 'soap'),
    ('Haushalt', 'cleaning_services'), ('Sonstiges', 'category'),
]
_GRUPPEN = [
    'Apfel|Äpfel|Birne|Birnen|Banane|Bananen|Orange|Orangen|Mandarine|Zitrone|Limette|Grapefruit|Kiwi|Mango|Ananas|Melone|Wassermelone|Weintrauben|Erdbeeren|Himbeeren|Heidelbeeren|Brombeeren|Ribisel|Johannisbeeren|Kirschen|Marillen|Aprikosen|Pfirsiche|Nektarinen|Zwetschken|Pflaumen|Datteln|Feigen|Granatapfel|Avocado|Tomate|Tomaten|Paradeiser|Kartoffel|Kartoffeln|Erdäpfel|Süßkartoffel|Zwiebel|Zwiebeln|Knoblauch|Karotte|Karotten|Möhre|Gurke|Gurken|Paprika|Zucchini|Melanzani|Aubergine|Brokkoli|Karfiol|Blumenkohl|Spinat|Mangold|Salat|Kopfsalat|Eisbergsalat|Vogerlsalat|Feldsalat|Rucola|Lauch|Porree|Sellerie|Stangensellerie|Kohlrabi|Radieschen|Rettich|Kren|Meerrettich|Rote Rüben|Rote Bete|Kürbis|Kraut|Weißkohl|Rotkraut|Rotkohl|Wirsing|Kohlsprossen|Rosenkohl|Spargel|Fenchel|Champignons|Pilze|Ingwer|Chili|Petersilie|Schnittlauch|Basilikum|Dill|Minze|Koriander|Rosmarin|Thymian|Erbsenschoten',
    'Brot|Vollkornbrot|Schwarzbrot|Weißbrot|Toast|Toastbrot|Semmel|Semmeln|Brötchen|Kornspitz|Laugenstange|Brezel|Baguette|Ciabatta|Fladenbrot|Pita|Croissant|Weckerl|Burgerbrötchen|Tortilla|Wraps|Knödelbrot|Striezel',
    'Milch|Vollmilch|Buttermilch|Hafermilch|Sojamilch|Mandelmilch|Joghurt|Naturjoghurt|Fruchtjoghurt|Skyr|Topfen|Quark|Schlagobers|Obers|Sahne|Sauerrahm|Saure Sahne|Crème fraîche|Creme fraiche|Butter|Margarine|Ei|Eier|Germ|Hefe|Pudding|Kefir|Kokosjoghurt',
    'Käse|Gouda|Emmentaler|Bergkäse|Parmesan|Mozzarella|Feta|Schafkäse|Frischkäse|Hüttenkäse|Camembert|Brie|Cheddar|Halloumi|Ricotta|Mascarpone|Wurst|Schinken|Salami|Extrawurst|Leberkäse|Speck|Frankfurter|Wiener|Debreziner|Bratwurst|Aufschnitt|Mortadella',
    'Fleisch|Faschiertes|Hackfleisch|Rindfleisch|Schweinefleisch|Hühnerbrust|Hähnchenbrust|Huhn|Hendl|Hähnchen|Pute|Putenschnitzel|Schnitzel|Steak|Gulaschfleisch|Rinderfilet|Schweinsfilet|Lamm|Ente|Fisch|Lachs|Forelle|Kabeljau|Zander|Saibling|Garnelen|Shrimps|Muscheln|Thunfischsteak',
    'Tiefkühlpizza|TK-Pizza|Tiefkühlspinat|TK-Spinat|Tiefkühlerbsen|TK-Erbsen|Tiefkühlgemüse|TK-Gemüse|Pommes|Pommes frites|Fischstäbchen|Eiscreme|Speiseeis|Tiefkühlbeeren|TK-Beeren|Blätterteig|Strudelteig|Kroketten',
    'Nudeln|Spaghetti|Penne|Fusilli|Farfalle|Tagliatelle|Lasagneplatten|Reis|Basmatireis|Risottoreis|Vollkornreis|Couscous|Bulgur|Quinoa|Hirse|Polenta|Grieß|Haferflocken|Linsen|Rote Linsen|Bohnen|Kichererbsen|Erbsen|Glasnudeln|Reisnudeln|Gnocchi|Spätzle|Semmelbrösel|Paniermehl',
    'Tomatenmark|Passata|Passierte Tomaten|Dosentomaten|Mais|Kidneybohnen|Weiße Bohnen|Thunfisch|Sardinen|Essiggurken|Oliven|Kapern|Pesto|Ketchup|Mayonnaise|Senf|Sojasauce|Worcestersauce|Tabasco|Kokosmilch|Brühe|Gemüsebrühe|Rindsuppe|Suppenwürfel|Apfelmus|Sauerkraut|Ajvar|Sriracha|Tomatensauce',
    'Salz|Pfeffer|Öl|Olivenöl|Sonnenblumenöl|Rapsöl|Essig|Balsamico|Zucker|Mehl|Weizenmehl|Dinkelmehl|Roggenmehl|Staubzucker|Puderzucker|Vanillezucker|Backpulver|Natron|Speisestärke|Maisstärke|Kakao|Backschokolade|Kuvertüre|Gelatine|Zimt|Muskat|Kümmel|Kreuzkümmel|Paprikapulver|Curry|Oregano|Lorbeer|Nelken|Vanille|Kurkuma|Sesam|Mohn|Kokosraspeln|Mandeln|Haselnüsse|Walnüsse|Rosinen',
    'Marmelade|Konfitüre|Honig|Nussnougatcreme|Nutella|Erdnussbutter|Müsli|Cornflakes|Granola|Schokolade|Kekse|Waffeln|Chips|Soletti|Popcorn|Gummibärchen|Bonbons|Zwieback|Müsliriegel|Studentenfutter',
    'Wasser|Mineralwasser|Soda|Saft|Apfelsaft|Orangensaft|Multivitaminsaft|Sirup|Limonade|Cola|Eistee|Kaffee|Espresso|Tee|Schwarztee|Grüntee|Kräutertee|Bier|Wein|Rotwein|Weißwein|Sekt|Prosecco|Alkoholfreies Bier',
    'Seife|Duschgel|Shampoo|Haarspülung|Deo|Zahnpasta|Zahnbürste|Zahnseide|Mundspülung|Handcreme|Sonnencreme|Bodylotion|Rasierer|Rasierschaum|Wattepads|Wattestäbchen|Tampons|Binden|Windeln|Feuchttücher|Taschentücher',
    'Klopapier|Toilettenpapier|Küchenrolle|Küchenpapier|Spülmittel|Geschirrspültabs|Spülmaschinensalz|Klarspüler|Waschmittel|Weichspüler|Allzweckreiniger|Glasreiniger|Schwamm|Schwämme|Müllbeutel|Alufolie|Frischhaltefolie|Backpapier|Gefrierbeutel|Servietten|Kerzen|Batterien|Zündhölzer',
]
WOERTERBUCH = {normalize_name(name): KATEGORIEN[i][0]
               for i, words in enumerate(_GRUPPEN) for name in words.split('|')}
VORRAT = {normalize_name(name) for name in ('Salz', 'Pfeffer', 'Öl', 'Olivenöl', 'Zucker', 'Mehl', 'Wasser')}


def seed(cur):
    from services.einkauf_sync import rang_initial
    for i, (name, icon) in enumerate(KATEGORIEN):
        cur.execute('INSERT IGNORE INTO einkauf_kategorien (name,icon,standard_rang) VALUES (%s,%s,%s)',
                    (name, icon, rang_initial(i)))
    cur.execute('SELECT id,name FROM einkauf_kategorien')
    ids = {row['name']: row['id'] for row in cur.fetchall()}
    names = {normalize_name(name): name for words in _GRUPPEN for name in words.split('|')}
    cur.executemany("""INSERT IGNORE INTO einkauf_artikel
        (name_norm,anzeigename,kategorie_id,vorrat,quelle) VALUES (%s,%s,%s,%s,'start')""",
                    [(name, names[name], ids[category], name in VORRAT) for name, category in WOERTERBUCH.items()])


def _stamm(name):
    for suffix in ('en', 'n', 's', 'e'):
        if name.endswith(suffix) and len(name) > len(suffix) + 2:
            return name[:-len(suffix)]
    return name


def kategorie_fuer(cur, name):
    norm = normalize_name(name)
    cur.execute('SELECT kategorie_id FROM einkauf_artikel WHERE name_norm=%s', (norm,))
    found = cur.fetchone()
    if found:
        return found['kategorie_id']
    last = norm.split()[-1] if norm else ''
    category = WOERTERBUCH.get(last)
    if category is None:
        category = next((cat for word, cat in WOERTERBUCH.items() if _stamm(word) == _stamm(last)), 'Sonstiges')
    cur.execute('SELECT id FROM einkauf_kategorien WHERE name=%s', (category,))
    row = cur.fetchone()
    return row['id'] if row else None

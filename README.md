# DocMiner

Iratokból (számla, szerződés, meghatalmazás) forráshelyes, AI-ready adatcsomag.
Minden kinyert érték mellett ott lesz a forrásoldal, a képterület és a bizonyosság;
a kétes értékeket ember nézi át.

| Modul | Feladat | Állapot |
|---|---|---|
| **DocSorter** | irattípus felismerése, metaadat-csoportok kiválasztása | 2. lépés |
| **DocMiner** | befogadás, felmérés, szöveg és táblák, képi részek, összerendelés, ellenőrzés | 1. lépés: befogadás + szöveg kész |
| **DocMaster** | felület: feltöltés, állapot, átnézés | váz |
| **DocExplorer** | szereplők összekapcsolása iratokon át | később |

## Indítás Windowson (terminál nélkül)

1. Egyszer: dupla kattintás az `Asztali_ikon_letrehozasa.bat` fájlra. Az asztalon megjelenik egy **DocMiner** ikon.
2. Utána mindig: dupla kattintás a **DocMiner** ikonra. Elindítja a Docker Desktopot (ha kell) és a DocMinert,
   majd megnyitja a DocMastert a böngészőben (http://localhost:8501).
3. Leállítás: `DocMiner_leallitas.bat`. Új változat letöltése: `DocMiner_frissites.bat`.

A DocMaster bal oldalán látszik, hogy próba- vagy éles (Google) módban fut, és a **Kapcsolat ellenőrzése**
gomb egy apró OCR- és modellhívással ellenőrzi a Google-kapcsolatot.

## Indítás

```bash
cp .env.example .env        # írd át a jelszót
docker compose up --build
```

- DocMiner API és dokumentációja: http://localhost:8000/docs
- DocMaster: http://localhost:8501 (Folyamat oldal: élő áttekintés lépésenként, hibák újraindítása; Iratok oldal: oldalkép és szöveg)
- Több feldolgozó: `docker compose up --scale worker=3`

Docker nélkül, fejlesztéshez (SQLite-tal):

```bash
pip install -e ".[dev]"
uvicorn docminer.api:app --reload        # API
python -m docminer.worker                # feldolgozó, külön terminálban
pytest                                   # tesztek
```

## Mi van kész (1. lépés)

- **Befogadás:** a fájltípust a tartalom alapján ismeri fel (PDF, PNG, JPEG, TIFF); elutasítja az üres,
  sérült, jelszavas, túl nagy vagy túl sok oldalas fájlt. Az azonos fájl (SHA-256) nem megy át kétszer.
  Az eredeti érintetlenül megmarad.
- **Oldalbontás:** oldalanként PNG-kép.
- **Szövegkinyerés (PyMuPDF):** oldalanként szöveg, szavak, blokkok és táblák koordinátákkal.
  A szövegréteg nélküli oldal `scanned` jelölést kap; ezt később a Document AI OCR dolgozza fel.
- **Folytatható feldolgozás:** minden irat minden lépése külön állapotot kap (`job_steps`).
  Leállás vagy hiba után onnan folytatja; a kész lépés nem fut újra. Hibánál legfeljebb
  `DOCMINER_MAX_STEP_ATTEMPTS` próba, utána `failed`, és a `POST /documents/{id}/retry` indítja újra.
  Több feldolgozó PostgreSQL-en `FOR UPDATE SKIP LOCKED`-del osztozik a soron; a leállt feldolgozó
  irata 30 perc után újra felvehető.
- **AI-ready csomag:** iratonként egy mappa `manifest.json`-nal (lásd `docminer/storage.py`).
- **Cserélhető modellek:** `config/models.yaml` lépésenként megadja a szolgáltatót, a modellt,
  a gondolkodási szintet és a tartalékmodellt. A `docminer/providers` réteg egy közös interfész;
  érvénytelen JSON-kimenetnél újrapróbál, majd tartalékra vált, és naplózza a próbálkozásokat.
  Most csak a hamis (`fake`) szolgáltató van bent: nincs hálózat, nincs költség.
- **Irattípusok YAML-ban:** `config/doctypes/` (számla, szerződés, meghatalmazás). Új típus = új fájl.
  A típusból modellfüggetlen JSON-séma készül (érték + oldal + bbox + bizonyosság mezőnként).
  A `verify: true` mezők (adószám, bankszámlaszám) mindig második ellenőrzést kapnak majd.

## Google Cloud (EU): OCR és valódi modell

- **OCR-lépés (`ocr`):** a szövegréteg nélküli oldalak oldalanként a Document AI OCR-hez mennek (EU-helyszín),
  koordinátás szavakkal; a digitális oldal nem megy ki. A már kifizetett oldalt újraindításkor nem küldi újra.
- **Havi korlátok:** OCR-oldal (`DOCMINER_OCR_MONTHLY_PAGE_LIMIT`), modellhívás és token
  (`DOCMINER_LLM_MONTHLY_CALL_LIMIT`, `..._TOKEN_LIMIT`). Fölöttük a hívás el sem indul, az irat hibás lesz
  üzenettel, és a korlát emelése után újraindítható. Felhasználás: `GET /usage` és a Folyamat oldal.
- **Gemini a Vertex AI EU-végpontján:** sémához kötött JSON-kimenet, token- és modellverzió-napló.
- **Profilváltás egy sorral:** `DOCMINER_MODELS_FILE=models.google.yaml` (valódi) vagy `models.yaml` (próba).
- Beállítás lépésenként és a kapcsolat ellenőrzése: [docs/GOOGLE_CLOUD.md](docs/GOOGLE_CLOUD.md).

## Következő lépések

1. Google Cloud (EU): Document AI OCR-adapter a szkennelt oldalakra, Gemini 3.8 Flash adapter (Vertex AI EU).
2. DocSorter + számla mezőkinyerése forráshellyel; mérés 20 saját számlán.
3. Szerződés, meghatalmazás, képi elemek (aláírás, bélyegző) kivágással.
4. Claude második olvasó, kétes lista.
5. DocMaster: átnézés, jóváhagyás, keresés.

## API röviden

| Végpont | Leírás |
|---|---|
| `POST /documents` | feltöltés (multipart `file`); duplikátumnál 200 + `duplicate: true` |
| `GET /documents?status=&q=` | iratlista szűréssel |
| `GET /documents/{id}` | állapot, lépések, oldalak |
| `GET /documents/{id}/pages/{n}/text` · `/layout` · `/image` | oldal szövege, koordinátái, képe |
| `GET /documents/{id}/manifest` · `/original` | AI-ready csomag, eredeti fájl |
| `POST /documents/{id}/retry` | hibás irat újraindítása |
| `GET /pipeline` | folyamat-áttekintés: szakaszok, számlálók, iratonkénti lépésállapot |
| `GET /config/doctypes` · `/config/models` | beállítások |

Lásd még: [docs/ESZKOZJEGYZEK.md](docs/ESZKOZJEGYZEK.md).

## Függetlenség

Saját fejlesztés, nyilvános eszközökre építve; munkáltatói kód, dokumentum vagy belső anyag nincs benne.

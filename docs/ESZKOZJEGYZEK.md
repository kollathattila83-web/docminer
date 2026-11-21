# Eszközjegyzék

Mely részek használhatók a DocMineren kívül is, és kinek érhetnek pénzt.

| Eszköz | Mit tud | Kinek érhet pénzt | Állapot |
|---|---|---|---|
| `docminer/intake.py` | Fájltípus tartalom szerint, sérült/jelszavas/túl nagy fájl kiszűrése, SHA-256 | Szkennermappa- vagy e-mail-befogadó bármely iktatórendszerhez | kész, függetlenül használható |
| `docminer/extract.py` | PDF-szöveg, szavak, táblák koordinátával; szkennelt oldal felismerése | Könyvelőiroda: digitális számlák gyors, OCR-költség nélküli feldolgozása | kész, függetlenül használható |
| `docminer/pipeline.py` + `queue.py` | Folytatható, lépésenkénti feldolgozás adatbázis-sorral, több feldolgozóval | Bármely tömeges, fizetős API-hívást végző munka (újrafuttatás nélkül) | kész; a lépések a DocMinerhez kötöttek |
| `docminer/providers/` | Közös MI-hívóréteg tartalékmodellel és JSON-séma ellenőrzéssel | Cégek, amelyek saját (Azure, vállalati) MI-fiókjukat akarják használni | interfész kész, valódi adapterek hiányoznak |
| `docminer/doctypes.py` + `config/doctypes/` | Irattípus = YAML-fájl, belőle modellfüggetlen séma | Ügyvédi és ingatlanirodák, HR: saját irattípus kód nélkül | kész |

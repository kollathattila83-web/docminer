# Google Cloud beállítása (EU)

Kulcsfájl vagy jelszó sehová nem kell: a programok a gépeden lévő
`gcloud` belépéssel (Application Default Credentials) futnak, a Docker ezt csak olvasásra kapja meg.

1. **Projekt:** console.cloud.google.com → projektválasztó → *New project* → `docminer`. Jegyezd fel a **Project ID**-t.
2. **Költségkeret:** *Billing → Budgets & alerts → Create budget*, **Alerts only**, havi összeg (pl. 10 000 Ft),
   figyelmeztetés 50 / 90 / 100%-nál. A Google leállító korlátja (Spend cap) csak néhány szolgáltatásra és
   szolgáltatásonként állítható be, a Document AI-ra nem. A tényleges megállítást ezért a DocMiner végzi:
   - `DOCMINER_OCR_MONTHLY_PAGE_LIMIT` (alap 1 000 oldal = a Document AI ingyenes kerete),
   - `DOCMINER_LLM_MONTHLY_CALL_LIMIT` (alap 2 000 hívás) és `DOCMINER_LLM_MONTHLY_TOKEN_LIMIT` (alap 5 millió token).
   Az aktuális felhasználás: `GET /usage`, és a DocMaster Folyamat oldalán.
3. **API-k:** *APIs & Services → Library*: **Vertex AI API** és **Cloud Document AI API** bekapcsolása.
4. **OCR-feldolgozó:** *Document AI → Processor gallery → Document OCR → Create*, név `docminer-ocr`, **Region: EU**. Jegyezd fel a **Processor ID**-t.
5. **Belépés a gépen:** telepítsd a Google Cloud CLI-t, majd:
   ```
   gcloud auth application-default login
   gcloud auth application-default set-quota-project <PROJECT_ID>
   ```
6. **.env** (a `.env.example` alapján):
   ```
   DOCMINER_MODELS_FILE=models.google.yaml
   GOOGLE_CLOUD_PROJECT=<PROJECT_ID>
   DOCMINER_DOCAI_PROCESSOR_ID=<PROCESSOR_ID>
   # Windows esetén:
   GCLOUD_CONFIG_DIR=C:/Users/<felhasználónév>/AppData/Roaming/gcloud
   ```
7. **Ellenőrzés:** `docker compose run --rm worker python -m docminer.check_gcp`
   Egy apró OCR- és egy modellhívást végez, és kiírja, mi működik.

## Mi hova megy

| Lépés | Szolgáltatás | Hely |
|---|---|---|
| OCR (csak szkennelt oldal) | Document AI OCR | `eu-documentai.googleapis.com` |
| Besorolás, mezőkinyerés | Gemini 3.8 Flash, Vertex AI | `aiplatform.eu.rep.googleapis.com` (EU több-régiós végpont) |

A digitális PDF szövege nem megy ki: azt a PyMuPDF helyben olvassa. A próbaprofilra
(`DOCMINER_MODELS_FILE=models.yaml`) visszaváltva semmi nem megy ki és nincs költség.

Ellenőrizendő az első éles futáskor: elérhető-e a `gemini-3.8-flash` az `eu` végponton.
Ha nem, a `config/models.google.yaml`-ban a `location` egy EU-régióra (pl. `europe-west4`) írható át.

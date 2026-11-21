"""DocMaster – egyszerű felület a DocMiner fölött (1. kör: váz).

Csak a DocMiner REST API-t használja, így később lecserélhető.
Most: feltöltés, iratlista állapottal, oldalak szövege és képe.
A kétes értékek jóváhagyása az 5. lépésben jön.
"""

import os

import requests
import streamlit as st

API = os.environ.get("DOCMINER_API_URL", "http://localhost:8000").rstrip("/")
STATUS_HU = {"queued": "sorban", "processing": "feldolgozás", "done": "kész", "failed": "hibás"}

st.set_page_config(page_title="DocMaster", layout="wide")
st.title("DocMaster")
st.caption("A feldolgozást a DocMiner végzi; ez a felület csak megjeleníti.")


def api(method: str, path: str, **kw):
    try:
        return requests.request(method, f"{API}{path}", timeout=60, **kw)
    except requests.RequestException as exc:
        st.error(f"A DocMiner nem érhető el ({API}): {exc}")
        st.stop()


with st.sidebar:
    st.header("Feltöltés")
    files = st.file_uploader(
        "PDF vagy kép", type=["pdf", "png", "jpg", "jpeg", "tif", "tiff"], accept_multiple_files=True
    )
    if files and st.button("Feltöltés"):
        for f in files:
            r = api("POST", "/documents", files={"file": (f.name, f.getvalue(), f.type or "application/octet-stream")})
            if r.status_code in (200, 201):
                if r.json().get("duplicate"):
                    st.info(f"{f.name}: már feltöltve korábban, nem dolgozzuk fel újra.")
                else:
                    st.success(f"{f.name}: sorba állítva.")
            else:
                st.error(f"{f.name}: {r.json().get('detail', r.text)}")

col_filter, col_refresh = st.columns([4, 1])
q = col_filter.text_input("Keresés fájlnévben")
if col_refresh.button("Frissítés"):
    st.rerun()

docs = api("GET", "/documents", params={"q": q or None}).json()
st.subheader(f"Iratok ({docs['total']})")
if not docs["items"]:
    st.write("Még nincs feltöltött irat.")
    st.stop()

st.dataframe(
    [
        {
            "Fájl": d["filename"],
            "Oldal": d["page_count"],
            "Állapot": STATUS_HU.get(d["status"], d["status"]),
            "Hiba": d["error"] or "",
        }
        for d in docs["items"]
    ],
    hide_index=True,
    use_container_width=True,
)

names = {d["id"]: d["filename"] for d in docs["items"]}
choice = st.selectbox("Irat megnyitása", options=list(names), format_func=names.get)
detail = api("GET", f"/documents/{choice}").json()

st.write("**Lépések**")
st.table(
    [
        {"Lépés": s["name"], "Állapot": s["status"], "Próba": s["attempts"], "Hiba": s["error"] or ""}
        for s in detail["steps"]
    ]
)
if detail["status"] == "failed" and st.button("Újraindítás"):
    api("POST", f"/documents/{choice}/retry")
    st.rerun()

if detail["pages"]:
    n = int(st.number_input("Oldal", min_value=1, max_value=len(detail["pages"]), value=1))
    page = detail["pages"][n - 1]
    left, right = st.columns(2)
    img = api("GET", f"/documents/{choice}/pages/{n}/image")
    if img.ok:
        left.image(img.content, caption=f"{n}. oldal ({page['kind'] or '…'})")
    txt = api("GET", f"/documents/{choice}/pages/{n}/text")
    right.text_area("Kinyert szöveg", txt.text if txt.ok else "(még nincs)", height=600)
    if page["kind"] == "scanned":
        right.warning("Szkennelt oldal: a szöveget a későbbi OCR-lépés adja (Document AI).")

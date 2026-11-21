"""DocMaster – egyszerű felület a DocMiner fölött.

Csak a DocMiner REST API-t használja, így később lecserélhető.
Oldalak: Folyamat (élő áttekintés), Jóváhagyás (irattípus elfogadása vagy javítása),
Iratok (feltöltés, oldalak szövege és képe). A kétes mezőértékek jóváhagyása később jön.
"""

import html
import os

import requests
import streamlit as st

API = os.environ.get("DOCMINER_API_URL", "http://localhost:8000").rstrip("/")
STATUS_HU = {"queued": "sorban", "processing": "feldolgozás", "done": "kész", "failed": "hibás"}
STEP_ICON = {"done": "✅", "running": "⏳", "pending": "🕓", "failed": "❌", "planned": "·"}

st.set_page_config(page_title="DocMaster", layout="wide")


def api(method: str, path: str, **kw):
    try:
        return requests.request(method, f"{API}{path}", timeout=60, **kw)
    except requests.RequestException as exc:
        st.error(f"A DocMiner nem érhető el ({API}): {exc}")
        st.stop()


def upload_sidebar():
    st.sidebar.header("Feltöltés")
    files = st.sidebar.file_uploader(
        "PDF vagy kép", type=["pdf", "png", "jpg", "jpeg", "tif", "tiff"], accept_multiple_files=True
    )
    if files and st.sidebar.button("Feltöltés"):
        for f in files:
            r = api("POST", "/documents", files={"file": (f.name, f.getvalue(), f.type or "application/octet-stream")})
            if r.status_code in (200, 201):
                if r.json().get("duplicate"):
                    st.sidebar.info(f"{f.name}: már feltöltve korábban, nem dolgozzuk fel újra.")
                else:
                    st.sidebar.success(f"{f.name}: sorba állítva.")
            else:
                st.sidebar.error(f"{f.name}: {r.json().get('detail', r.text)}")


# --- Folyamat ---------------------------------------------------------------

FLOW_CSS = """
<style>
.dm-flow{display:flex;flex-wrap:wrap;gap:6px;align-items:stretch;margin:4px 0 12px}
.dm-stage{flex:0 1 160px;min-width:130px;border:1px solid #d0d5dd;border-radius:10px;padding:8px 10px;background:#fff;color:#1d2433}
.dm-stage.planned{background:#f4f5f7;color:#8a93a3;border-style:dashed}
.dm-stage.has-failed{border-color:#d92d20;box-shadow:0 0 0 1px #d92d20 inset}
.dm-stage.has-running{border-color:#2e6be6}
.dm-mod{font-size:11px;text-transform:uppercase;letter-spacing:.04em;opacity:.7}
.dm-label{font-weight:600;font-size:14px;margin:2px 0 4px}
.dm-desc{font-size:11px;opacity:.75;margin-bottom:6px;line-height:1.3}
.dm-counts{font-size:12px;display:flex;gap:8px;flex-wrap:wrap}
.dm-bar{height:5px;border-radius:3px;background:#e6e8ec;margin-top:6px;overflow:hidden}
.dm-bar>span{display:block;height:100%;background:#12a150}
.dm-arrow{align-self:center;color:#98a2b3;font-size:16px}
</style>
"""


def flow_html(stages: list[dict], total: int) -> str:
    parts = [FLOW_CSS, '<div class="dm-flow">']
    for i, s in enumerate(stages):
        c = s["counts"]
        cls = ["dm-stage"]
        if not s["implemented"]:
            cls.append("planned")
        if c.get("failed"):
            cls.append("has-failed")
        if c.get("running"):
            cls.append("has-running")
        if s["implemented"]:
            counts = (
                f'<span title="kész">✅ {c.get("done", 0)}</span>'
                f'<span title="folyamatban">⏳ {c.get("running", 0)}</span>'
                f'<span title="vár">🕓 {c.get("pending", 0)}</span>'
                f'<span title="hibás">❌ {c.get("failed", 0)}</span>'
            )
            pct = round(100 * c.get("done", 0) / total) if total else 0
            bar = f'<div class="dm-bar"><span style="width:{pct}%"></span></div>'
        else:
            counts, bar = "<span>hamarosan</span>", ""
        parts.append(
            f'<div class="{" ".join(cls)}">'
            f'<div class="dm-mod">{html.escape(s["module"])}</div>'
            f'<div class="dm-label">{html.escape(s["label"])}</div>'
            f'<div class="dm-desc">{html.escape(s["description"])}</div>'
            f'<div class="dm-counts">{counts}</div>{bar}</div>'
        )
        if i < len(stages) - 1:
            parts.append('<div class="dm-arrow">→</div>')
    parts.append("</div>")
    return "".join(parts)


def render_pipeline():
    ov = api("GET", "/pipeline").json()
    docs, stages, items = ov["documents"], ov["stages"], ov["items"]
    total, by = docs["total"], docs["by_status"]

    m = st.columns(5)
    m[0].metric("Összes irat", total)
    m[1].metric("Sorban", by["queued"])
    m[2].metric("Feldolgozás alatt", by["processing"])
    m[3].metric("Kész", by["done"])
    m[4].metric("Hibás", by["failed"])

    finished = by["done"] + by["failed"]
    st.progress(finished / total if total else 0.0, text=f"Haladás: {finished} / {total} irat végzett")

    st.markdown(flow_html(stages, total), unsafe_allow_html=True)
    st.caption("A szaggatott keretű lépések a terv későbbi körei; a sáv a kész iratok aránya.")

    if not items:
        st.info("Még nincs feltöltött irat. Tölts fel egyet a bal oldalon.")
        return

    st.subheader("Iratok lépésenként")
    impl = [s for s in stages if s["implemented"]]
    rows = []
    for it in items:
        row = {"Fájl": it["filename"], "Állapot": STATUS_HU.get(it["status"], it["status"]), "Oldal": it["page_count"]}
        for s in impl:
            row[s["label"]] = STEP_ICON.get(it["stages"][s["key"]]["status"], "?")
        row["OCR-re vár"] = ", ".join(map(str, it["scanned_pages"])) or ""
        rows.append(row)
    st.dataframe(rows, hide_index=True, use_container_width=True)
    st.caption("✅ kész · ⏳ folyamatban · 🕓 vár · ❌ hibás. „OCR-re vár”: a szkennelt oldalak sorszáma, ezeket a későbbi OCR-lépés olvassa.")

    failed = [it for it in items if it["status"] == "failed"]
    if failed:
        st.subheader(f"Hibás iratok ({len(failed)})")
        for it in failed:
            c1, c2 = st.columns([5, 1])
            c1.error(f"**{it['filename']}** — {it['error']}")
            if c2.button("Újraindítás", key=f"retry-{it['id']}"):
                api("POST", f"/documents/{it['id']}/retry")
                st.rerun()


def page_pipeline():
    st.title("Folyamat")
    st.caption("Élő áttekintés: hol tart az egyes iratok feldolgozása.")
    live = st.toggle("Élő frissítés (3 mp)", value=True)

    @st.fragment(run_every=3 if live else None)
    def _live():
        render_pipeline()

    _live()


# --- Jóváhagyás ---------------------------------------------------------------

TYPE_STATUS_HU = {"suggested": "jóváhagyásra vár", "approved": "elfogadva", "corrected": "javítva"}


def _conf_label(c) -> str:
    if c is None:
        return "–"
    level = "magas" if c >= 0.85 else "közepes" if c >= 0.6 else "alacsony"
    return f"{round(c * 100)}% ({level})"


def page_review():
    st.title("Irattípus jóváhagyása")
    st.caption("A gép javasol, ember dönt. Minden döntésből tanítópélda lesz.")

    stats = api("GET", "/review/doctypes/stats").json()
    m = st.columns(4)
    m[0].metric("Jóváhagyásra vár", stats["suggested"])
    m[1].metric("Elfogadva", stats["approved"])
    m[2].metric("Javítva", stats["corrected"])
    m[3].metric("Javaslat pontossága", f"{round(stats['accuracy'] * 100)}%" if stats["accuracy"] is not None else "–")

    reviewer = st.text_input("Ki dönt? (név, opcionális)", key="reviewer")
    queue = api("GET", "/review/doctypes", params={"limit": 200}).json()
    choices: dict = queue["choices"]

    if not queue["items"]:
        st.success("Nincs jóváhagyásra váró irat.")
    else:
        st.subheader(f"Jóváhagyásra vár ({queue['total']}) – a legbizonytalanabb elöl")
        names = {d["id"]: f"{d['filename']} · {choices.get(d['suggested_type'], d['suggested_type'])} · {_conf_label(d['suggested_confidence'])}" for d in queue["items"]}
        doc_id = st.selectbox("Irat", options=list(names), format_func=names.get)
        doc = next(d for d in queue["items"] if d["id"] == doc_id)
        detail = api("GET", f"/documents/{doc_id}").json()

        left, right = st.columns([3, 2])
        with right:
            st.markdown(f"**Javasolt típus:** {choices.get(doc['suggested_type'], doc['suggested_type'])}")
            st.markdown(f"**Bizonyosság:** {_conf_label(doc['suggested_confidence'])}")
            if doc["suggested_reason"]:
                st.markdown(f"**Indoklás:** {doc['suggested_reason']}")
            keys = list(choices)
            default = keys.index(doc["suggested_type"]) if doc["suggested_type"] in keys else 0
            picked = st.radio("Típus", options=keys, index=default, format_func=choices.get, key=f"pick-{doc_id}")
            label = "Elfogadom" if picked == doc["suggested_type"] else "Javítom erre"
            if st.button(label, type="primary", key=f"save-{doc_id}"):
                r = api("POST", f"/documents/{doc_id}/doctype", json={"doc_type": picked, "reviewer": reviewer or None})
                if r.ok:
                    st.toast(f"{doc['filename']}: {choices[picked]} ({TYPE_STATUS_HU[r.json()['type_status']]})")
                    st.rerun()
                else:
                    st.error(r.json().get("detail", r.text))
        with left:
            pages = detail["pages"]
            if pages:
                n = int(st.number_input("Oldal", min_value=1, max_value=len(pages), value=1, key=f"page-{doc_id}"))
                img = api("GET", f"/documents/{doc_id}/pages/{n}/image")
                if img.ok:
                    st.image(img.content, caption=f"{n}. / {len(pages)} oldal")
                txt = api("GET", f"/documents/{doc_id}/pages/{n}/text")
                with st.expander("Kinyert szöveg"):
                    st.text(txt.text if txt.ok and txt.text.strip() else "(nincs szövegréteg, OCR-re vár)")

    with st.expander("Korábbi döntések (módosíthatók az Iratok oldalon)"):
        done = []
        for status in ("approved", "corrected"):
            done += api("GET", "/review/doctypes", params={"status": status, "limit": 100}).json()["items"]
        if done:
            st.dataframe(
                [
                    {
                        "Fájl": d["filename"],
                        "Típus": choices.get(d["doc_type"], d["doc_type"]),
                        "Javaslat": choices.get(d["suggested_type"], d["suggested_type"]),
                        "Állapot": TYPE_STATUS_HU.get(d["type_status"], d["type_status"]),
                        "Döntött": d["reviewed_by"] or "",
                    }
                    for d in done
                ],
                hide_index=True,
                use_container_width=True,
            )
            st.download_button(
                "Tanítópéldák letöltése (JSONL)",
                data=api("GET", "/training/doctype.jsonl").content,
                file_name="doctype_training.jsonl",
                mime="application/jsonl",
            )
        else:
            st.write("Még nincs döntés.")


def doctype_editor(detail: dict, doc_id: str):
    """Iratok oldal: a már eldöntött típus utólagos módosítása."""
    if not detail.get("type_status"):
        return
    choices = api("GET", "/review/doctypes", params={"limit": 1}).json()["choices"]
    current = detail["doc_type"] or detail["suggested_type"]
    st.write(
        f"**Irattípus:** {choices.get(current, current)} "
        f"({TYPE_STATUS_HU.get(detail['type_status'], detail['type_status'])})"
    )
    keys = list(choices)
    c1, c2 = st.columns([3, 1])
    picked = c1.selectbox("Típus módosítása", keys, index=keys.index(current) if current in keys else 0, format_func=choices.get, key=f"edit-{doc_id}")
    if c2.button("Mentés", key=f"edit-save-{doc_id}"):
        api("POST", f"/documents/{doc_id}/doctype", json={"doc_type": picked, "reviewer": st.session_state.get("reviewer") or None})
        st.rerun()


# --- Iratok -----------------------------------------------------------------


def page_documents():
    st.title("Iratok")
    col_filter, col_refresh = st.columns([4, 1])
    q = col_filter.text_input("Keresés fájlnévben")
    if col_refresh.button("Frissítés"):
        st.rerun()

    docs = api("GET", "/documents", params={"q": q or None}).json()
    st.subheader(f"Iratok ({docs['total']})")
    if not docs["items"]:
        st.write("Még nincs feltöltött irat.")
        return

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

    doctype_editor(detail, choice)

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


upload_sidebar()
nav = st.navigation(
    [
        st.Page(page_pipeline, title="Folyamat", icon="🔄", default=True),
        st.Page(page_review, title="Jóváhagyás", icon="✔️", url_path="jovahagyas"),
        st.Page(page_documents, title="Iratok", icon="📄", url_path="iratok"),
    ]
)
nav.run()

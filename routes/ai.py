import re, json, base64
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from config import CLAUDE_MODEL, MAX_UPLOAD_MB, UPLOAD_DIR
from services.claude_service import (
    get_claude, check_api_key, parse_claude,
    clean_html, PROMPT_URL, PROMPT_IMAGE, SEARCH_SYSTEM,
)
from services.image_service import (
    extract_best_image, download_image, search_recipe_image, resize_and_save,
)
from auth import require_auth
import httpx

router = APIRouter(dependencies=[Depends(require_auth)])


@router.post("/api/analysiere-url")
def analysiere_url(body: dict):
    url = body.get("url", "").strip()
    if not url:
        raise HTTPException(400, "URL fehlt")
    check_api_key()

    try:
        with httpx.Client(follow_redirects=True, timeout=20.0,
                          headers={"User-Agent": "Mozilla/5.0"}) as client:
            resp = client.get(url)
            raw_html = resp.text
    except Exception as e:
        raise HTTPException(400, f"URL nicht abrufbar: {e}")

    downloaded_image = None
    img_url = extract_best_image(raw_html[:30000], url)
    if img_url:
        downloaded_image = download_image(img_url, url)

    clean_text = clean_html(raw_html)

    quelle_typ = "web"
    if "youtube.com" in url or "youtu.be" in url:
        quelle_typ = "youtube"
    elif "tiktok.com" in url:
        quelle_typ = "tiktok"
    elif "instagram.com" in url:
        quelle_typ = "instagram"
    elif any(x in url for x in ["chefkoch","allrecipes","lecker.de"]):
        quelle_typ = "rezeptseite"

    claude = get_claude()
    msg = claude.messages.create(
        model=CLAUDE_MODEL, max_tokens=2048,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": PROMPT_URL, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": f"\n\n(URL: {url})\n---\n{clean_text}\n---"},
        ]}]
    )
    try:
        result = parse_claude(msg.content[0].text)
    except Exception as e:
        raise HTTPException(500, f"Claude-Antwort konnte nicht geparst werden: {e}")
    if result.get("fehler"):
        if downloaded_image:
            p = UPLOAD_DIR / downloaded_image
            if p.exists():
                p.unlink()
        raise HTTPException(422, result["fehler"])

    if not downloaded_image:
        downloaded_image = search_recipe_image(result.get("titel", ""))

    result.update({"quelle_url": url, "quelle_typ": quelle_typ,
                   "downloaded_image": downloaded_image})
    return result


@router.post("/api/analysiere-bild")
async def analysiere_bild(file: UploadFile = File(...)):
    check_api_key()
    ext = Path(file.filename).suffix.lower()
    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"Datei zu groß (max {MAX_UPLOAD_MB} MB)")

    claude = get_claude()

    if ext == ".pdf":
        b64 = base64.standard_b64encode(data).decode()
        msg = claude.messages.create(
            model=CLAUDE_MODEL, max_tokens=2000,
            messages=[{"role": "user", "content": [
                {"type": "document", "source": {"type": "base64",
                 "media_type": "application/pdf", "data": b64}},
                {"type": "text", "text": PROMPT_IMAGE, "cache_control": {"type": "ephemeral"}},
            ]}]
        )
    else:
        media_map = {".jpg":"image/jpeg",".jpeg":"image/jpeg",".png":"image/png",
                     ".webp":"image/webp",".gif":"image/gif",".heic":"image/jpeg"}
        if ext not in media_map:
            raise HTTPException(400, f"Format nicht unterstützt: {ext} (JPG, PNG, WebP, PDF)")
        b64 = base64.standard_b64encode(data).decode()
        msg = claude.messages.create(
            model=CLAUDE_MODEL, max_tokens=2000,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                 "media_type": media_map[ext], "data": b64}},
                {"type": "text", "text": PROMPT_IMAGE, "cache_control": {"type": "ephemeral"}},
            ]}]
        )

    try:
        result = parse_claude(msg.content[0].text)
    except Exception as e:
        raise HTTPException(500, f"Claude-Antwort konnte nicht geparst werden: {e}")
    if result.get("fehler"):
        raise HTTPException(422, result["fehler"])

    result["quelle_typ"] = "pdf-import" if ext == ".pdf" else "bild-import"

    if ext != ".pdf":
        import_fname = resize_and_save(data, ext)
        internet_fname = search_recipe_image(result.get("titel", ""))
        if internet_fname:
            result["downloaded_image"] = internet_fname
            result["import_image"] = import_fname
        else:
            result["downloaded_image"] = import_fname
            result["import_image"] = None

    return result


@router.post("/api/rezept-suche")
def rezept_suche(body: dict):
    anfrage = body.get("anfrage", "").strip()
    if not anfrage:
        raise HTTPException(400, "Anfrage fehlt")
    check_api_key()

    claude = get_claude()
    messages = [{"role": "user", "content": f"Suche 2-3 Rezepte für: {anfrage}"}]
    final_text = ""

    for _ in range(6):
        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=5000,
            system=SEARCH_SYSTEM,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=messages,
        )
        for block in response.content:
            if getattr(block, "type", None) == "text" and block.text.strip():
                final_text = block.text
        if response.stop_reason == "end_turn":
            break
        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = [
                {"type": "tool_result", "tool_use_id": block.id,
                 "content": f"Suchergebnisse für '{block.input.get('query', anfrage)}' abgerufen."}
                for block in response.content
                if getattr(block, "type", None) == "tool_use"
            ]
            if tool_results:
                messages.append({"role": "user", "content": tool_results})
            continue
        break

    if not final_text:
        raise HTTPException(500, "Keine Antwort erhalten — bitte erneut versuchen")

    try:
        raw = re.sub(r"```json\s*|```\s*", "", final_text.strip()).strip()
        try:
            results = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r'(\[.*\]|\{.*\})', raw, re.DOTALL)
            if m:
                results = json.loads(m.group(1))
            else:
                raise ValueError("Kein JSON gefunden")
        if isinstance(results, dict):
            results = [results]
    except Exception as e:
        raise HTTPException(500, f"Antwort konnte nicht geparst werden: {e}")

    if len(results) == 1 and results[0].get("fehler"):
        raise HTTPException(422, results[0]["fehler"])

    results = [r for r in results if not r.get("fehler")]
    if not results:
        raise HTTPException(422, "Keine passenden Rezepte gefunden")

    return results

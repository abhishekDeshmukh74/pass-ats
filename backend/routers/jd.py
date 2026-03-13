from fastapi import APIRouter, HTTPException
from backend.models import ScrapeRequest, TextResponse
from backend.services.scraper import scrape_url
import httpx

router = APIRouter()


@router.post("/scrape-jd", response_model=TextResponse)
async def scrape_jd(body: ScrapeRequest):
    url = str(body.url).strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")

    try:
        text = scrape_url(url)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch URL (HTTP {exc.response.status_code}).",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Network error while fetching URL: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to scrape URL: {exc}") from exc

    if not text.strip():
        raise HTTPException(status_code=422, detail="No text content could be extracted from the URL.")

    return TextResponse(text=text)

"""Admin dashboard page. The page itself is public but empty: every piece of data
comes from the /admin routes, which require the admin key typed into the page."""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)

_PAGE = Path(__file__).resolve().parent.parent / "static" / "admin.html"
_HEADERS = {
    # Inline script and style only, data only from this origin, never framed.
    "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


@router.get("/admin/ui")
def admin_page():
    return HTMLResponse(_PAGE.read_text(encoding="utf-8"), headers=_HEADERS)

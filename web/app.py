"""The web server: a handful of JSON answers and the pages that show them.

    python -m web                                   on this computer
    uvicorn web.app:app --host 0.0.0.0 --port 10000   on a host

Every /api/ answer is plain data. Market data always goes  visitor -> limits -> DataService (cache)
-> MarketSource, so there is one place to change the limits and one place to change the source.
"""

import logging
import os
import sys
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

import insight_core as core

from . import WEB_VERSION, shape
from .config import Settings
from .limits import BadRequest, NotFound, VisitorLimiter, clean_query, clean_range, clean_symbol, clean_symbols
from .service import DataService
from .source import SourceBusy, SourceFailed

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATIC = os.path.join(HERE, "static")
log = logging.getLogger("insight.web")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'self'",
}


def theme_css():
    """The Milton colours as CSS variables, written from the same palette the Windows app uses."""
    def block(mode):
        colors = core.build_palette(mode)
        page, ink, accent = colors["BG"], colors["INK"], colors["ACCENT"]
        # words on an accent-coloured button: the page colour if it reads well, otherwise ink
        readable = core.contrast(page, accent) >= 2.4 or core.contrast(page, accent) >= core.contrast(ink, accent)
        lines = [f"  --{name.lower().replace('_', '-')}: {colors[name]};" for name in core.COLOR_NAMES]
        lines.append(f"  --on-accent: {page if readable else ink};")
        lines.append(f"  color-scheme: {mode};")
        return "\n".join(lines)

    light, dark = block("light"), block("dark")
    return ("/* Written by web/app.py from insight_core.THEMES. Change the colours there. */\n"
            f":root {{\n{light}\n}}\n"
            f":root[data-theme=\"dark\"] {{\n{dark}\n}}\n"
            "@media (prefers-color-scheme: dark) {\n"
            f"  :root:not([data-theme=\"light\"]) {{\n{dark}\n  }}\n}}\n")


def memory_mb():
    """How much memory this server is using, when the system will say."""
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/self/statm") as f:
                return round(int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1e6, 1)
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                    (name, ctypes.c_size_t) for name in (
                        "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                        "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage",
                        "PeakPagefileUsage")]

            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            kernel32 = ctypes.WinDLL("kernel32")
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi = ctypes.WinDLL("psapi")
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            if psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                return round(counters.WorkingSetSize / 1e6, 1)
    except Exception:
        pass
    return None


def create_app(source=None, settings=None, clock=time.time, sleep=time.sleep):
    """Build the server. Tests pass their own source, settings and clock."""
    settings = settings or Settings.from_env()
    if source is None:
        from .yahoo import YahooSource
        source = YahooSource()
    service = DataService(source, per_minute=settings.source_per_minute, burst=settings.source_burst,
                          max_wait=settings.source_max_wait, max_entries=settings.cache_entries,
                          max_numbers=settings.cache_numbers, clock=clock, sleep=sleep)
    visitors = VisitorLimiter(settings.visitor_per_minute, settings.visitor_burst, clock=clock)
    css = theme_css()

    @asynccontextmanager
    async def lifespan(app):
        log.info("Insight by Milton web %s started. Data source: %s", WEB_VERSION, source.name)
        yield
        totals = service.status()["totals"]
        log.info("Stopping after %d s. Fetches: %s", int(clock() - service.started), totals)

    app = FastAPI(title="Insight by Milton", version=WEB_VERSION, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.service, app.state.visitors, app.state.settings = service, visitors, settings

    def address_of(request):
        if settings.visitor_address == "forwarded":     # behind a host's proxy the socket is the proxy
            first = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            if first:
                return first[:64]
        return request.client.host if request.client else "unknown"

    def problem(status, code, message, retry_after=None):
        headers = {"Cache-Control": "no-store"}
        if retry_after:
            headers["Retry-After"] = str(int(retry_after))
        return JSONResponse({"error": {"code": code, "message": message, "retry_after": retry_after}},
                            status_code=status, headers=headers)

    @app.middleware("http")
    async def limits_and_headers(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and path != "/api/health":
            allowed, wait = visitors.allow(address_of(request))
            if not allowed:
                return problem(429, "too_many_requests",
                               "This address is asking very quickly. Please wait a moment and try again.", wait)
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(BadRequest)
    async def bad_request(request, error):
        return problem(400, "bad_request", str(error))

    @app.exception_handler(NotFound)
    async def not_found(request, error):
        return problem(404, "not_found", str(error))

    @app.exception_handler(SourceBusy)
    async def source_busy(request, error):
        return problem(503, "source_busy", str(error), error.retry_after)

    @app.exception_handler(SourceFailed)
    async def source_failed(request, error):
        return problem(502, "source_failed", str(error), 30)

    # --- data -------------------------------------------------------------------------------------
    @app.api_route("/api/health", methods=["GET", "HEAD"])
    def health():
        """Answers without touching the data source, so a host can check it as often as it likes."""
        return {"status": "ok", "app": core.APP_NAME, "web_version": WEB_VERSION,
                "uptime_seconds": int(clock() - service.started)}

    @app.get("/api/snapshot")
    def snapshot():
        priced, _ = service.quotes([symbol for _, symbol, _ in core.SNAPSHOT])
        return shape.snapshot(service, priced)

    @app.get("/api/quotes")
    def quotes(symbols: str = ""):
        wanted = clean_symbols(symbols)
        priced, missing = service.quotes(wanted)
        return shape.quotes(service, priced, missing)

    @app.get("/api/history/{symbol}")
    def history(symbol: str, range: str = "1Y"):
        symbol, range_key = clean_symbol(symbol), clean_range(range)
        answer = service.history(symbol, range_key)
        if answer.value is None:
            raise NotFound(f"No price data found for “{symbol}”.")
        return shape.history(service, symbol, range_key, answer)

    @app.get("/api/stock/{symbol}")
    def stock(symbol: str):
        symbol = clean_symbol(symbol)
        details = service.details(symbol)
        if details.value is None:
            raise NotFound(f"Couldn't find “{symbol}”.")
        earnings = None
        if details.value.get("quoteType") == "EQUITY":      # funds, indexes and crypto have no earnings
            try:
                earnings = service.earnings(symbol)
            except (SourceBusy, SourceFailed):
                earnings = None                              # the rest of the page is still worth showing
        return shape.stock(service, symbol, details, earnings)

    @app.get("/api/search")
    def search(q: str = ""):
        query = clean_query(q)
        return shape.search(service, query, service.search(query))

    @app.get("/api/status")
    def status(request: Request):
        """How the data fetches have gone since the server started."""
        report = service.status()
        report["visitors"] = dict(visitors.status(), address_from=settings.visitor_address,
                                  forwarding_steps_on_this_request=len(
                                      [p for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]))
        report["memory_mb"] = memory_mb()
        report["web_version"] = WEB_VERSION
        return report

    # --- pages ------------------------------------------------------------------------------------
    def page(name):
        return FileResponse(os.path.join(STATIC, name), headers={"Cache-Control": "no-cache"})

    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    def home():
        return page("index.html")

    @app.api_route("/status", methods=["GET", "HEAD"], include_in_schema=False)
    def status_page():
        return page("status.html")

    @app.get("/theme.css", include_in_schema=False)
    def theme():
        return Response(css, media_type="text/css", headers={"Cache-Control": "public, max-age=3600"})

    def shared_file(route, *parts):
        path = os.path.join(ROOT, *parts)

        @app.get(route, include_in_schema=False)
        def send():
            if not os.path.isfile(path):
                return Response(status_code=404)
            return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})

    shared_file("/assets/logo.png", "assets", "logo.png")
    shared_file("/assets/logo-dark.png", "assets", "logo-dark.png")
    shared_file("/favicon.ico", "icon.ico")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


if not logging.getLogger("insight.web").handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(_handler)
    log.setLevel(logging.INFO)

app = create_app()

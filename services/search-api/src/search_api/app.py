import time
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import StringConstraints

from search_api import results
from search_api.cache import TtlCache
from search_api.meili import Meili, SearchUnavailable
from search_api.query import Search
from search_api.ratelimit import RateLimiter
from search_api.settings import Settings

Text = Annotated[str, Query(max_length=200)]
Value = Annotated[str, StringConstraints(max_length=100)]
Values = Annotated[list[Value] | None, Query(max_length=10)]
Year = Annotated[int | None, Query(ge=1, le=9999)]
YEAR_FIELDS = ("year_from", "year_to")


def create_app(settings: Settings) -> FastAPI:
    meili = Meili(settings.meili_url, settings.meili_key)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await meili.close()

    app = FastAPI(title="search-api", lifespan=lifespan)
    cache = TtlCache(settings.cache_ttl_seconds, settings.cache_max_entries, settings.cache_max_bytes)
    limiter = RateLimiter(settings.rate_limit_per_minute, settings.rate_limit_window_seconds, settings.rate_limit_max_clients)

    def client_of(request: Request) -> str:
        """The address the nearest trusted proxy saw; entries before it are whatever the client claimed."""
        forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
        if len(forwarded) >= settings.trusted_proxies:
            return forwarded[-settings.trusted_proxies]
        return request.client.host if request.client else "unknown"

    @app.middleware("http")
    async def protect(request: Request, call_next):
        if not request.url.path.startswith("/api/search"):
            return await call_next(request)
        wait = limiter.check(client_of(request))
        if wait is not None:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Slow down and try again shortly."},
                headers={"Retry-After": str(wait)},
            )
        key = request.url.path + "?" + "&".join(sorted(request.url.query.split("&")))
        shared = {"Cache-Control": f"public, max-age={int(settings.cache_ttl_seconds)}"}
        cached = cache.get(key)
        if cached is not None:
            return Response(cached, media_type="application/json", headers={**shared, "X-Cache": "HIT"})
        response = await call_next(request)
        if response.status_code != 200:
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])
        cache.put(key, body)
        return Response(body, media_type="application/json", headers={**shared, "X-Cache": "MISS"})

    @app.exception_handler(SearchUnavailable)
    async def unavailable(request: Request, error: SearchUnavailable):
        return JSONResponse(status_code=503, content={"detail": "Search is not available right now"})

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> dict:
        if not await meili.healthy():
            raise HTTPException(status_code=503, detail="Search is not available")
        return {"status": "ok"}

    def paging(page: int, page_size: int | None) -> tuple[int, int]:
        size = settings.default_page_size if page_size is None else min(page_size, settings.max_page_size)
        return page, size

    def years(year_from: int | None, year_to: int | None) -> None:
        if year_from is not None and year_to is not None and year_from > year_to:
            raise HTTPException(status_code=422, detail="year_from must not be after year_to")

    async def run(search: Search, *, hits: bool = True) -> dict:
        found = await meili.search(search.scope, search.body(hits=hits))
        answer = {
            "page": found.get("page", search.page),
            "page_size": search.page_size,
            "total": found.get("totalHits", 0),
            "total_pages": found.get("totalPages", 0),
            "facets": {k: v for k, v in found.get("facetDistribution", {}).items() if k not in YEAR_FIELDS},
            # The earliest and latest years on offer, for a year slider, instead of a long list of years.
            "facet_stats": {k: v for k, v in found.get("facetStats", {}).items() if k in YEAR_FIELDS},
        }
        if hits:
            answer["hits"] = [
                results.document_hit(hit, settings.iiif_base_url) if search.scope == "documents" else results.subject_hit(hit)
                for hit in found["hits"]
            ]
        return answer

    @app.get("/api/search/documents")
    async def search_documents(
        q: Text = "",
        verified_only: bool = False,
        ship_type: Values = None,
        builder: Values = None,
        place: Values = None,
        document_type: Values = None,
        year_from: Year = None,
        year_to: Year = None,
        page: Annotated[int, Query(ge=1, le=1000)] = 1,
        page_size: Annotated[int | None, Query(ge=1)] = None,
    ) -> dict:
        years(year_from, year_to)
        page, size = paging(page, page_size)
        return await run(
            Search(
                "documents", q,
                {"ship_type": ship_type or [], "builder": builder or [], "place": place or [], "document_type": document_type or []},
                verified_only, year_from, year_to, page, size,
            )
        )

    def subject_search(q, kind, ship_type, builder, place, year_from, year_to, page, page_size) -> Search:
        years(year_from, year_to)
        page, size = paging(page, page_size)
        filters = {"kind": [kind] if kind else [], "ship_type": ship_type or [], "builder": builder or [], "place": place or []}
        return Search("subjects", q, filters, False, year_from, year_to, page, size)

    @app.get("/api/search/subjects")
    async def search_subjects(
        q: Text = "",
        kind: Literal["ship", "organisation"] | None = None,
        ship_type: Values = None,
        builder: Values = None,
        place: Values = None,
        year_from: Year = None,
        year_to: Year = None,
        page: Annotated[int, Query(ge=1, le=1000)] = 1,
        page_size: Annotated[int | None, Query(ge=1)] = None,
    ) -> dict:
        return await run(subject_search(q, kind, ship_type, builder, place, year_from, year_to, page, page_size))

    @app.get("/api/search/suggest")
    async def suggest(q: Annotated[str, Query(max_length=100)] = "") -> dict:
        """Up to eight completions as someone types: Subjects by any name they have carried, then Documents by title."""
        if not q.strip():
            return {"suggestions": []}
        marks = {"highlightPreTag": results.START, "highlightPostTag": results.END}
        subjects = await meili.search(
            "subjects",
            {"q": q, "limit": 5, "attributesToHighlight": ["names"], "attributesToRetrieve": ["id", "entity", "name", "names"], **marks},
        )
        documents = await meili.search("documents", {"q": q, "limit": 3, "attributesToRetrieve": ["id", "title"]})
        suggestions = []
        for hit in subjects["hits"]:
            matched = next((n for n in hit.get("_formatted", {}).get("names", []) if results.START in n), None)
            suggestions.append(
                {"type": hit["entity"], "id": hit["id"], "text": hit["name"], "matched_name": results.plain(matched) if matched else None}
            )
        suggestions += [{"type": "document", "id": hit["id"], "text": hit["title"], "matched_name": None} for hit in documents["hits"]]
        return {"suggestions": suggestions[:8]}

    @app.get("/api/search/facets")
    async def facets(
        scope: Literal["documents", "subjects"],
        q: Text = "",
        verified_only: bool = False,
        kind: Literal["ship", "organisation"] | None = None,
        ship_type: Values = None,
        builder: Values = None,
        place: Values = None,
        year_from: Year = None,
        year_to: Year = None,
    ) -> dict:
        if scope == "documents":
            years(year_from, year_to)
            search = Search(
                "documents", q,
                {"ship_type": ship_type or [], "builder": builder or [], "place": place or []},
                verified_only, year_from, year_to, 1, 1,
            )
        else:
            search = subject_search(q, kind, ship_type, builder, place, year_from, year_to, 1, 1)
        answer = await run(search, hits=False)
        return {"scope": scope, "facets": answer["facets"], "facet_stats": answer["facet_stats"], "total": answer["total"]}

    return app

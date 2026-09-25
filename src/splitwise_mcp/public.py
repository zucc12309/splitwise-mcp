"""Static registration pages and an explicitly locked, credential-free setup deployment."""

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}
STYLE = "body{font:18px/1.6 system-ui,sans-serif;max-width:760px;margin:60px auto;padding:24px;color:#182e29;background:#f6faf8}h1{line-height:1.2}a{color:#126b56}.status{padding:16px;background:#e3eee9;border-radius:8px}"


def page(title: str, body: str):
    return HTMLResponse(
        f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>{STYLE}</style><main>{body}</main></html>',
        headers=HEADERS,
    )


async def homepage(request):
    return page(
        "LifeAdmin Personal",
        """<h1>LifeAdmin Personal</h1>
<p>A private, non-commercial integration for the owner's Splitwise account.</p>
<p>Read groups, expenses and balances, and prepare expense drafts for review.
Posting an expense requires separate human approval. This integration does not transfer money.</p>
<p class="status">This homepage does not grant access to account data. MCP access requires configured owner authentication, credentials and durable storage.</p>
<p><a href="/privacy">Privacy</a> · <a href="https://github.com/zucc12309/splitwise-mcp">Source and setup guide</a> · <a href="https://github.com/zucc12309/splitwise-mcp/issues">Support</a></p>""",
    )


async def privacy(request):
    return page(
        "Privacy — LifeAdmin Personal",
        """<h1>Privacy</h1>
<p>This is an owner-only personal prototype. When configured, it reads requested account IDs, display names, group membership, expense descriptions, dates, currencies and shares from Splitwise. Requested information is returned to the owner's MCP client and assistant, whose privacy and retention policies also apply.</p>
<p>Expense drafts and operation outcomes are stored in the owner's configured database. Drafts expire after 15 minutes; an operator can scrub old draft details after 30 days while preserving the duplicate-prevention ledger. Uncertain outcomes are retained for manual reconciliation.</p>
<p>No analytics or internal language-model calls are used. The integration does not intentionally return emails or contact details, and does not log credentials or financial descriptions. Hosting providers may retain operational request logs.</p>
<p>Splitwise may collect and use API usage data under its own terms and privacy policy. Disconnect by stopping the integration and revoking its personal API key; this does not delete upstream records. Review the source documentation before deleting local state or backups.</p>
<p>For deletion or support, contact the owner through the repository's support page. Do not publish credentials or financial details in public issues.</p><p><a href="/">Home</a></p>""",
    )


def setup_app():
    async def health(request):
        return JSONResponse({"status": "setup_required", "mcp_enabled": False}, headers=HEADERS)

    async def disabled(request):
        return JSONResponse(
            {
                "error": "setup_required",
                "message": "MCP is disabled until owner authentication, Splitwise credentials and durable storage are configured.",
            },
            status_code=503,
            headers=HEADERS,
        )

    return Starlette(
        routes=[
            Route("/", homepage),
            Route("/privacy", privacy),
            Route("/health", health),
            Route("/mcp", disabled, methods=["GET", "POST", "DELETE", "OPTIONS", "HEAD"]),
            Route(
                "/mcp/{path:path}", disabled, methods=["GET", "POST", "DELETE", "OPTIONS", "HEAD"]
            ),
        ]
    )

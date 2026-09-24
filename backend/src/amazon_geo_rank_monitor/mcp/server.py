from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token

from .tools import RankMcpTools


def _register_tools(
    server: MCPServer,
    tools_factory: Callable[[], RankMcpTools],
) -> None:
    @server.tool()
    async def check_rank(
        marketplace: str,
        keyword: str,
        asins: list[str],
        geo_profile_ids: list[str],
        search_depth: int = 100,
        provider_mode: str = "managed",
    ) -> dict:
        """Check current Amazon geographic organic rank."""
        return await tools_factory().check_rank(
            marketplace=marketplace,
            keyword=keyword,
            asins=asins,
            geo_profile_ids=geo_profile_ids,
            search_depth=search_depth,
            provider_mode=provider_mode,
        )

    @server.tool()
    def list_geo_profiles() -> list[dict]:
        """List geographic profiles available to the current tenant."""
        return tools_factory().list_geo_profiles()

    @server.tool()
    def create_monitor(
        name: str,
        marketplace: str,
        keyword: str,
        asins: list[str],
        geo_profile_ids: list[str],
        search_depth: int = 100,
        provider_mode: str = "managed",
        schedule: str | None = None,
    ) -> dict:
        """Create a persistent Amazon rank monitor."""
        return tools_factory().create_monitor(
            name=name,
            marketplace=marketplace,
            keyword=keyword,
            asins=asins,
            geo_profile_ids=geo_profile_ids,
            search_depth=search_depth,
            provider_mode=provider_mode,
            schedule=schedule,
        )

    @server.tool()
    def run_monitor(monitor_id: str) -> dict:
        """Queue a saved monitor for execution."""
        return tools_factory().run_monitor(monitor_id=monitor_id)

    @server.tool()
    def get_rank_run(run_id: str) -> dict:
        """Get a completed or in-progress rank run."""
        return tools_factory().get_rank_run(run_id=run_id)

    @server.tool()
    def get_rank_history(limit: int = 50) -> list[dict]:
        """Get recent rank runs for the current tenant."""
        return tools_factory().get_rank_history(limit=limit)


def build_local_mcp_server(tools: RankMcpTools) -> MCPServer:
    server = MCPServer("Amazon Geo Rank Monitor")
    _register_tools(server, lambda: tools)
    return server


def build_streamable_http_app(
    *,
    services: Any,
    auth: Any,
    token_verifier: Any,
    tenant_resolver: Callable[[Any], str | None] | None,
):
    if auth is None or token_verifier is None or tenant_resolver is None:
        raise ValueError(
            "Streamable HTTP MCP requires AuthSettings, TokenVerifier, "
            "and tenant_resolver"
        )
    server = MCPServer(
        "Amazon Geo Rank Monitor",
        auth=auth,
        token_verifier=token_verifier,
    )

    def tools_factory() -> RankMcpTools:
        token = get_access_token()
        if token is None:
            raise PermissionError("authenticated MCP access token required")
        owner_id = tenant_resolver(token)
        if not owner_id:
            raise PermissionError("MCP access token is not mapped to a tenant")
        return RankMcpTools(services=services, owner_id=owner_id)

    _register_tools(server, tools_factory)
    return server.streamable_http_app()

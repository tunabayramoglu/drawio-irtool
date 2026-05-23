"""Entry point: `python -m irtool_mcp` starts the MCP server on stdio."""

from .server import mcp


if __name__ == "__main__":
    mcp.run()

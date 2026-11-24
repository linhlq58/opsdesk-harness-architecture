"""Temporary in-process tools (M05 §5.2): stand-ins for later capabilities.

* ``faq.search_faq``: a static FAQ, replaced by retrieval in M10.
* ``devices.list_my_devices``: a fake device list, replaced by the asset system
  behind MCP in M08.

"Temporary adapters, permanent contracts" (roadmap rule 3): each stub goes through
``harness_tool``, returns a ``ToolResult`` and emits the same tool events as a real
tool. When the real capability arrives, only the tool's *inside* changes; the tool
name, its ``ToolResult`` and every agent that uses it stay the same.

The data is loaded **once at startup** from ``data/stubs`` and handed to a tool
factory (``make_search_faq(entries)``): a broken YAML file is a startup error, not a
surprise on the first question, and tests can pass a few hand-made entries.
"""

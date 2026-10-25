"""The steps, in order: storage, unpack, configure, bootloader, finish.

Each module exposes check(ctx) -> [errors], apply(ctx), summary(ctx) -> str.
`storage` also has ensure_mounted(ctx) for a resume. The shared facts a later
step needs (the devices, the UUIDs, the layout) live in ctx.state["storage"]
and are copied into the journal so a resume finds them.
"""

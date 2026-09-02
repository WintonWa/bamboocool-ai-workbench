# Organic Soft-Tech design system

Status: active shared design source of truth in the Bamboocool project archive.

This directory turns the selected Google Stitch system into a durable project reference. Future UI work should start here instead of reconstructing the style from screenshots or memory.

## Reading order

1. `DESIGN.md` — exact Stitch design-system export.
2. `tokens.css` — named, copyable tokens for implementation.
3. `components.md` — BambooCool-specific component and density decisions.
4. `references.md` — source screens, node IDs, screenshots, HTML, and QA evidence.

The original machine-fetched export is preserved at `Stitch源文件/DESIGN.md`. The copy in this directory is intentionally placed in a discoverable location for future tasks.

## Authority order

When guidance appears to conflict, use this order:

1. The user's current explicit request.
2. `DESIGN.md` for brand language, palette, typography, spacing, elevation, and Organic shape principles.
3. `components.md` for this dashboard's approved density adaptation.
4. Existing production-ready patterns in the current frontend implementation.
5. Stitch reference screenshots and HTML for visual comparison.

Do not combine tokens from another design system without an explicit decision. New experiments should be built in an independent copy or branch so this baseline stays recoverable.

## Change workflow

- Identify the closest existing component before creating a new one.
- Use the named Organic tokens rather than untracked hex values.
- Compare affected screens with the relevant source reference.
- Preserve business content and behavior while changing presentation.
- Update these docs when a new reusable component, token, or exception is approved.

Last synchronized from Stitch: 2026-08-02.

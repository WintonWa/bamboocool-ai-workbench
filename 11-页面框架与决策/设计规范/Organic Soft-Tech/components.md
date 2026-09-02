# BambooCool component profile

The Stitch system is intentionally very rounded and spacious. This dashboard keeps that character while using a slightly denser profile so operational information remains visible at 1280px.

## Approved runtime profile

| Surface | Project baseline | Organic principle |
| --- | --- | --- |
| Application canvas | Warm ivory `#fbf9f8` | Light, airy base |
| Sidebar | 244px, warm off-white | Quiet navigation rail |
| Active navigation | Full pill, deep green | Strong but friendly selection |
| Large section panels | 28px radius | Broad soft container |
| KPI cards | 26px radius | Pebble-like summary surface |
| Insight/trend panels | 22px radius | Nested radius below parent |
| Anomaly cards | 22px radius | Soft interactive cards |
| Suggestion/copy cards | 20px radius | Compact nested surface |
| Buttons and chips | Full pill | Clear tactile controls |
| Inputs | Soft fill, minimal border | Focus ring supplies emphasis |

Do not increase every container to 40–48px automatically. Those values describe the pure Stitch system; the table above is the approved density adaptation for this workbench. Maintain concentric hierarchy: parent radius > nested card radius > icon/control radius.

## Typography

- Display and section headings: Plus Jakarta Sans, usually 600–700 weight.
- Body, labels, controls, and data provenance: Be Vietnam Pro, usually 400–700 weight.
- Chinese fallback: Microsoft YaHei, then PingFang SC.
- Headline tracking should be tight. Small labels may use modest positive tracking.
- Use size, weight, and whitespace for hierarchy before introducing another color.

## Color usage

- Deep green is reserved for active navigation, primary actions, one high-emphasis KPI, and important icon moments.
- Mint surfaces communicate positive, forecast, derived, or AI-enhanced states.
- Warm whites and gray-green neutrals should occupy most of the page.
- Error and warning colors remain semantic accents; do not turn the dashboard into a red/yellow/green traffic-light system.

## Cards and layout

- Keep an 8px base rhythm and at least 12px around deeply rounded elements.
- Use 20–32px internal padding depending on information density.
- Prefer whitespace and tonal separation to divider-heavy layouts.
- Shadows must stay ambient and low-opacity. Borders should be subtle and green-tinted.
- At desktop size, preserve the 12-column logic and the existing two-column anomaly/suggestion composition until 1040px.

## Controls and states

- Primary buttons: deep-green pill with white text.
- Secondary buttons: white or pale-green pill with low-contrast border.
- Chips/tags: full pill, tinted background, bold semantic text.
- Hover: small lift or tonal change; avoid dramatic scaling.
- Focus: visible green-tinted focus ring.
- Disabled or simulated states must remain legible and must not appear executable when they are not.

## Data and charts

- Use deep green, mint, gray-green, and restrained semantic accents.
- Preserve source/status labels such as real, simulated, and derived.
- Do not invent business data solely to fill a layout.
- Charts should remain readable without relying on color alone.

## Assets and icons

- Operator avatar: `public/operator-avatar.jpg`.
- Use the repository's existing icon library for UI icons.
- Do not substitute emoji, CSS drawings, handcrafted SVGs, or placeholder boxes for visible assets.

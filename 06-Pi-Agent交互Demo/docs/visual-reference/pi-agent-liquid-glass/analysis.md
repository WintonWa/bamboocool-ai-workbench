# Visual reference analysis

These three generated images are implementation references only. They are not runtime assets and their generated body copy is not a source of product facts.

## Shared system

- Canvas: very pale mint-to-ivory field with diffuse radial light, no visible texture noise.
- Reading width: mobile-first 390px rhythm with roughly 20px gutters.
- Text: deep forest green; display headings use a bold geometric sans; body stays dark gray-green.
- Corners: 28–32px on primary glass surfaces, 18–22px on nested controls, full pill for the main action.
- Depth: white rim highlight, low-opacity green ambient shadow, transparent fill, no harsh black drop shadow.
- Accent: a restrained chartreuse highlight is used only for step indexes and completion cues.
- Motion implication: pointer-follow highlight on the hero pill; staggered reveal for numbered sections.

## Hero reference

- The first viewport has one clear focal sequence: metadata → two-line headline → large glass stage → pill action.
- Headline is substantially larger than body copy and uses tight line-height/tracking.
- The glass stage is tall and calm; the pill occupies less than half the stage width.
- The pill combines a translucent fill, thin white rim, slight cyan/pink edge separation, and a soft lower-right green shadow.
- Implementation should keep the title smaller than the generated mockup on a 390px viewport so it wraps cleanly without clipping.
- The generated English metadata is a visual placeholder; final copy follows the approved design document.

## Content rhythm reference

- Three rhythms are intentionally different:
  1. translucent white rounded card with compact features;
  2. open section with checklist and no outer card;
  3. deep-green emphasis panel.
- Index blocks are square-rounded rather than circular and stay visually aligned with section headings.
- Body text uses generous line-height and wide gaps; avoid dense card walls.
- The generated WebGL/front-end-engineer sentence is incorrect for this project and must not be implemented.
- Visible icons in the generated mockup are not copied; the production page uses typographic bullets and existing semantic DOM.

## Live demo reference

- One main glass interaction surface contains the selector, recommended prompt, trace, answer, and composer.
- Trace uses a simple vertical sequence with small numbered markers and thin separators.
- The answer is visually separated by tonal fill rather than another heavy card.
- Controls are large enough for touch; the send action is deep green.
- The generated product name and step labels are placeholders; production continues to render real API data and existing tool labels.

## Implementation extraction

- Page max width: 760px for editorial content, up to 920px for the live interaction surface.
- Main gutters: 18px mobile, 28px tablet/desktop.
- Section spacing: 20–28px between related blocks, 72–96px between major chapters.
- Primary glass: rgba(255,255,255,.58) with 18–28px blur where supported.
- Rim: 1px solid rgba(255,255,255,.78), plus a subtle green-tinted outline.
- Shadow: 0 24px 70px rgba(23,45,33,.10).
- Hero pill: minimum 64px high mobile, 76px desktop, full radius.
- Reduced motion: remove pointer translation and reveal transitions while preserving all states.


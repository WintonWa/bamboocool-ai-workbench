---
name: Organic Soft-Tech
colors:
  surface: '#fbf9f8'
  surface-dim: '#dbd9d9'
  surface-bright: '#fbf9f8'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f5f3f3'
  surface-container: '#efeded'
  surface-container-high: '#eae8e7'
  surface-container-highest: '#e4e2e2'
  on-surface: '#1b1c1c'
  on-surface-variant: '#424844'
  inverse-surface: '#303030'
  inverse-on-surface: '#f2f0f0'
  outline: '#737973'
  outline-variant: '#c2c8c2'
  surface-tint: '#4d6455'
  primary: '#172d21'
  on-primary: '#ffffff'
  primary-container: '#2d4336'
  on-primary-container: '#97af9f'
  inverse-primary: '#b3cdbb'
  secondary: '#5b5f5e'
  on-secondary: '#ffffff'
  secondary-container: '#dde0de'
  on-secondary-container: '#5f6362'
  tertiary: '#013010'
  on-tertiary: '#ffffff'
  tertiary-container: '#1b4724'
  on-tertiary-container: '#86b589'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#cfe9d6'
  primary-fixed-dim: '#b3cdbb'
  on-primary-fixed: '#0a2014'
  on-primary-fixed-variant: '#354c3e'
  secondary-fixed: '#e0e3e1'
  secondary-fixed-dim: '#c4c7c5'
  on-secondary-fixed: '#181c1b'
  on-secondary-fixed-variant: '#434846'
  tertiary-fixed: '#bdefbe'
  tertiary-fixed-dim: '#a2d3a4'
  on-tertiary-fixed: '#002109'
  on-tertiary-fixed-variant: '#24502c'
  background: '#fbf9f8'
  on-background: '#1b1c1c'
  surface-variant: '#e4e2e2'
typography:
  headline-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 40px
    fontWeight: '700'
    lineHeight: 48px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 40px
    letterSpacing: -0.01em
  headline-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  body-lg:
    fontFamily: Be Vietnam Pro
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Be Vietnam Pro
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  label-md:
    fontFamily: Be Vietnam Pro
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 20px
    letterSpacing: 0.01em
  headline-lg-mobile:
    fontFamily: Plus Jakarta Sans
    fontSize: 30px
    fontWeight: '700'
    lineHeight: 36px
rounded:
  sm: 0.5rem
  DEFAULT: 1rem
  md: 1.5rem
  lg: 2rem
  xl: 3rem
  full: 9999px
spacing:
  base: 8px
  container-padding: 32px
  gutter: 24px
  stack-sm: 12px
  stack-md: 24px
  stack-lg: 48px
---

## Brand & Style
The design system focuses on an ultra-friendly, approachable, and organic aesthetic. By combining high-end "Soft-Tech" influences with a deep nature-inspired palette, the interface feels both sophisticated and welcoming.

The style is characterized by **Maximal Roundedness**, moving away from traditional rigid grids toward a fluid, "pebble-like" interface. It utilizes a mix of **Minimalism** and **Modern Corporate** aesthetics, emphasizing heavy whitespace and soft, tactile surfaces to ensure the deep brand green remains the focal point without feeling heavy.

## Colors
The palette is anchored by the brand's deep forest green. To maintain a friendly and light feel despite the dark primary color, the system utilizes a vast amount of off-white/mint-tinted secondary space.

- **Primary**: Used for key actions, brand moments, and high-emphasis icons.
- **Secondary**: A soft, minty-white used for large background containers to reduce eye strain.
- **Tertiary**: A muted accent green for highlights, progress indicators, and soft button states.
- **Neutral**: Grays are slightly warmed to stay consistent with the organic theme.

## Typography
The typography uses soft, geometric sans-serifs to complement the ultra-rounded UI. **Plus Jakarta Sans** provides a modern, friendly voice for headers, while **Be Vietnam Pro** offers exceptional readability for body text with a warm, contemporary feel.

- Use **Tight Letter Spacing** for headlines to maintain a cohesive "block" look.
- **Line Heights** are generous to allow the layout to breathe, reinforcing the minimalist philosophy.

## Layout & Spacing
The layout follows a **Fluid Grid** model with significant inner padding to accommodate the extra-large corner radii. 

- **Desktop**: 12-column grid, 1200px max-width, 32px margins.
- **Mobile**: Single column, 20px margins.
- **Rhythm**: All spacing must be multiples of 8px. Because of the "Super-Ellipse" feel of the components, avoid tight grouping (less than 12px) to prevent visual crowding at the corners.

## Elevation & Depth
This design system avoids harsh shadows. Depth is communicated through **Tonal Layers** and subtle **Ambient Shadows**.

1. **Base Level**: The main background (#FFFFFF or #f4f7f5).
2. **Raised Level**: Cards and containers use an extremely soft, diffused shadow (Blur: 30px, Opacity: 4%, Color: #2d4336).
3. **Interactive Level**: Buttons and active inputs use a slightly more defined shadow to invite interaction.
4. **Overlay**: Modals use a heavy backdrop blur (20px) rather than a dark overlay to maintain the "light and airy" feel.

## Shapes
The defining characteristic of this design system is its **Ultra-Rounded Geometry**. 

- **Full Radius**: Buttons, Chips, and Input Fields must use a full pill shape (999px) or a minimum of 32px.
- **Containers & Cards**: Larger surfaces utilize a minimum radius of 32px to 48px to ensure they feel organic and soft.
- **Nested Elements**: Ensure inner elements have a slightly smaller radius than their parent containers to maintain concentric visual harmony.

## Components

- **Buttons**: Primary buttons are solid #2d4336 with white text. Shape must be a full pill (rounded-full). Padding should be 16px vertical and 32px horizontal.
- **Input Fields**: Soft-tinted backgrounds (#f4f7f5) with no borders, only a focus ring in the primary color. Height should be a minimum of 56px to match the bold rounded aesthetic.
- **Cards**: Large 40px corner radius. Use high padding (32px+) to prevent content from getting cut off by the deep curves.
- **Chips/Tags**: Small pill shapes with #2d4336 at 10% opacity and bold primary-colored text.
- **Lists**: Items should be separated by whitespace rather than dividers, utilizing rounded hover states (24px radius).
- **Navigation Bar**: A floating pill-shaped container centered at the top or bottom of the screen, utilizing backdrop blur.

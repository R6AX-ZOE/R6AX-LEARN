# Design System Inspired by Apple

## 1. Visual Theme & Atmosphere

Apple's website is a masterclass in controlled drama — vast expanses of pure black and near-white serve as cinematic backdrops for products that are photographed as if they were sculptures in a gallery. The design philosophy is reductive to its core: every pixel exists in service of the product, and the interface itself retreats until it becomes invisible. This is not minimalism as aesthetic preference; it is minimalism as reverence for the object.

The typography anchors everything. San Francisco (SF Pro Display for large sizes, SF Pro Text for body) is Apple's proprietary typeface, engineered with optical sizing that automatically adjusts letterforms depending on point size. At display sizes (56px), weight 600 with a tight line-height of 1.07 and subtle negative letter-spacing (-0.28px) creates headlines that feel machined rather than typeset — precise, confident, and unapologetically direct. At body sizes (17px), the tracking loosens slightly (-0.374px) and line-height opens to 1.47, creating a reading rhythm that is comfortable without ever feeling slack.

The color story is starkly binary. Product sections alternate between pure black (`#000000`) backgrounds with white text and light gray (`#f5f5f7`) backgrounds with near-black text (`#1d1d1f`). This creates a cinematic pacing — dark sections feel immersive and premium, light sections feel open and informational. The only chromatic accent is Apple Blue (`#0071e3`), reserved exclusively for interactive elements: links, buttons, and focus states. This singular accent color in a sea of neutrals gives every clickable element unmistakable visibility.

**Key Characteristics:**
- SF Pro Display/Text with optical sizing — letterforms adapt automatically to size context
- Binary light/dark section rhythm: black (`#000000`) alternating with light gray (`#f5f5f7`)
- Single accent color: Apple Blue (`#0071e3`) reserved exclusively for interactive elements
- Product-as-hero photography on solid color fields — no gradients, no textures, no distractions
- Extremely tight headline line-heights (1.07-1.14) creating compressed, billboard-like impact
- Full-width section layout with centered content — the viewport IS the canvas
- Pill-shaped CTAs (980px radius) creating soft, approachable action buttons
- Generous whitespace between sections allowing each product moment to breathe

## 2. Color Palette & Roles

### Primary
- **Pure Black** (`#000000`): Hero section backgrounds, immersive product showcases. The darkest canvas for the brightest products.
- **Light Gray** (`#f5f5f7`): Alternate section backgrounds, informational areas. Not white — the slight blue-gray tint prevents sterility.
- **Near Black** (`#1d1d1f`): Primary text on light backgrounds, dark button fills. Slightly warmer than pure black for comfortable reading.

### Interactive
- **Apple Blue** (`#0071e3`): `--sk-focus-color`, primary CTA backgrounds, focus rings. The ONLY chromatic color in the interface.
- **Link Blue** (`#0066cc`): `--sk-body-link-color`, inline text links. Slightly darker than Apple Blue for text-level readability.
- **Bright Blue** (`#2997ff`): Links on dark backgrounds. Higher luminance for contrast on black sections.

### Text
- **White** (`#ffffff`): Text on dark backgrounds, button text on blue/dark CTAs.
- **Near Black** (`#1d1d1f`): Primary body text on light backgrounds.
- **Black 80%** (`rgba(0, 0, 0, 0.8)`): Secondary text, nav items on light backgrounds. Slightly softened.
- **Black 40%** (`rgba(0, 0, 0, 0.4)`): Disabled states, placeholder text on light backgrounds.
- **White 70%** (`rgba(255, 255, 255, 0.7)`): Secondary text on dark backgrounds.
- **White 40%** (`rgba(255, 255, 255, 0.4)`): Disabled states, placeholder text on dark backgrounds.

### Surface (dark)
- **Card Dark** (`#272729`): Dark UI elements like cards and search fields.
- **Card Dark Alt** (`#2a2a2d`): Alternate dark surface for subtle differentiation.

## 3. Typography System

### Font Stack
- **Display (20px+)**: `SF Pro Display`, `-apple-system`, `BlinkMacSystemFont`, `"Segoe UI"`, `Roboto`, `"Helvetica Neue"`, `Arial`, sans-serif
- **Text (<20px)**: `SF Pro Text`, `-apple-system`, `BlinkMacSystemFont`, `"Segoe UI"`, `Roboto`, `"Helvetica Neue"`, `Arial`, sans-serif
- **Fallback**: The system-ui stack ensures that even without SF Pro installed, the OS-native system font renders (San Francisco on Apple devices, Segoe UI on Windows, Roboto on Android)

### Type Scale

| Token | Size | Weight | Line-Height | Letter-Spacing | Usage |
|-------|------|--------|-------------|----------------|-------|
| Display 1 | 56px | 600 (Semibold) | 1.07 | -0.28px | Hero product headline |
| Display 2 | 40px | 600 (Semibold) | 1.1 | -0.22px | Section heading |
| Display 3 | 28px | 400 (Regular) | 1.14 | 0.196px | Product card title |
| Display 4 | 24px | 400 (Regular) | 1.17 | 0.24px | Subheading |
| Title 1 | 21px | 400 (Regular) | 1.19 | 0.38px | Hero subtitle |
| Title 2 | 17px | 400 (Regular) | 1.47 | -0.374px | Body copy, description |
| Title 3 | 14px | 400 (Regular) | 1.43 | -0.224px | Small description, caption |
| Title 4 | 12px | 400 (Regular) | 1.33 | -0.12px | Nav links, fine print |

### Available Weights
- **100 (Thin)** / **200 (Extra Light)** / **300 (Light)**: Reserved for very specific large display treatments — rare
- **400 (Regular)**: The workhorse weight for body text, subtitles, navigation
- **500 (Medium)**: Emphasis within body text, secondary button text
- **600 (Semibold)**: Primary headlines, primary button text, key callouts
- **700 (Bold)**: Used rarely for extreme emphasis — Apple avoids heavy weights

### Typeface Selection Logic
```css
/* Apple selects typeface based on computed text size: */
text-size < 20px → SF Pro Text (optimized for readability)
text-size ≥ 20px → SF Pro Display (optimized for visual impact)
```
This boundary is critical — at 19px you get Text metrics, at 20px you get Display metrics. The letterforms themselves change subtly at this boundary (ascenders shorten, spacing tightens). While custom fonts can't auto-switch like Apple's, the CSS font-family can be set per component depending on intended size context.

## 4. Component Design

### Buttons
**Primary Button (CTA)**
- Background: Apple Blue (`#0071e3`)
- Text: White (`#ffffff`), 14px SF Pro Text, weight 400
- Padding: 8px 15px (creating ~44px touch height on mobile)
- Radius: 8px (full rectangle)
- Hover: `#0077ed` (slightly lighter blue)
- Focus: `2px solid #0071e3` outline
- Active: `#006edb` (slightly darker blue)
- Use: Primary actions — "Buy", "Shop", "Save"

**Secondary Button (Outline)**
- Background: transparent
- Text: White on dark bg, `#1d1d1f` on light bg
- Border: 1px solid matching text color
- Padding: 8px 15px
- Radius: 8px
- Hover: `rgba(0,0,0,0.05)` fill on light, `rgba(255,255,255,0.15)` on dark
- Use: Secondary actions — "Learn more", "View pricing"

**Pill CTA (Link-style)**
- Container: inline-flex with 980px border-radius
- Content: Text + right arrow (>)
- Text: 14px SF Pro Text, `#0066cc` (light bg) or `#2997ff` (dark bg)
- Padding: a few pixels for clickable area (typically 4px 8px)
- Hover: underline
- Use: "Learn more >" links under product descriptions

**Ghost Button (Text only)**
- Style: Bare text with no container
- Text: `#0066cc` (light) / `#2997ff` (dark), 14px, weight 400
- Underline on hover
- Use: Product grid "Learn more >" and "Shop >" links

### Chips & Tags
- Background: `rgba(0, 0, 0, 0.08)` light, `rgba(255, 255, 255, 0.12)` dark
- Text: 12px SF Pro Text, weight 400
- Radius: 5px
- Padding: 0 4px
- No border, no shadow
- Use: Feature labels, product tags

### Input & Search
- Background: `#f5f5f7` (light), `#272729` with `rgba(255,255,255,0.04)` inset border (dark)
- Text: 14px SF Pro Text, weight 400
- Padding: 6px 10px
- Radius: 8px
- Focus: Blue border/glow
- Placeholder: `rgba(0,0,0,0.4)` or `rgba(255,255,255,0.4)`

### Toggle, Switch & Checkbox
- Track: `rgba(116, 116, 128, 0.32)` (light), `rgba(255, 255, 255, 0.18)` (dark)
- Active Track: `#0071e3` (or `#30d158` for green variants)
- Thumb: White (`#ffffff`)
- Checkbox: 4px border-radius, `#0066cc` checked state
- Use: System controls, preference panels

### Slider & Progress
- Track: `rgba(116, 116, 128, 0.32)`
- Active Track: `#0071e3`
- Thumb: White, circular, with shadow on hover
- Use: Volume, brightness, progress indication

### Segmented Control
- Background: `rgba(116, 116, 128, 0.32)`
- Selected Segment: White (`#ffffff`) with `rgba(0,0,0,0.1)` shadow
- Text: 12px SF Pro Text, weight 400
- Radius: 5px
- Use: Filter/sort toggle, view switching

### Media Controls
- Background: `rgba(210, 210, 215, 0.64)`, white bg, black text
- Shape: Circle (50% radius on container)
- Size: Matches touch target (44x44px minimum)
- Icon: White or black glyph on translucent background
- Active: Scale(0.95) or similar press effect
- Use: Play/pause, carousel arrows

### Cards & Containers
- Background: `#f5f5f7` (light) or `#272729`-`#2a2a2d` (dark)
- Border: none (borders are rare in Apple's system)
- Radius: 5px-8px
- Shadow: `rgba(0, 0, 0, 0.22) 3px 5px 30px 0px` for elevated product cards
- Content: centered, generous padding
- Hover: no standard hover state — cards are static, links within them are interactive

### Navigation
- Background: `rgba(0, 0, 0, 0.8)` (translucent dark) with `backdrop-filter: saturate(180%) blur(20px)`
- Height: 48px (compact)
- Text: `#ffffff` at 12px, weight 400
- Active: underline on hover
- Logo: Apple logomark (SVG) centered or left-aligned, 17x48px viewport
- Mobile: collapses to hamburger with full-screen overlay menu
- The nav floats above content, maintaining its dark translucent glass regardless of section background

### Image Treatment
- Products on solid-color fields (black or white) — no backgrounds, no context, just the object
- Full-bleed section images that span the entire viewport width
- Product photography at extremely high resolution with subtle shadows
- Lifestyle images confined to rounded-corner containers (12px+ radius)

### Distinctive Components

**Product Hero Module**
- Full-viewport-width section with solid background (black or `#f5f5f7`)
- Product name as the primary headline (SF Pro Display, 56px, weight 600)
- One-line descriptor below in lighter weight
- Two pill CTAs side by side: "Learn more" (outline) and "Buy" / "Shop" (filled)

**Product Grid Tile**
- Square or near-square card on contrasting background
- Product image dominating 60-70% of the tile
- Product name + one-line description below
- "Learn more" and "Shop" link pair at bottom

**Feature Comparison Strip**
- Horizontal scroll of product variants
- Each variant as a vertical card with image, name, and key specs
- Minimal chrome — the products speak for themselves

## 5. Layout Principles

### Spacing System
- Base unit: 8px
- Scale: 2px, 4px, 5px, 6px, 7px, 8px, 9px, 10px, 11px, 14px, 15px, 17px, 20px, 24px
- Notable characteristic: the scale is dense at small sizes (2-11px) with granular 1px increments, then jumps in larger steps. This allows precise micro-adjustments for typography and icon alignment.

### Grid & Container
- Max content width: approximately 980px (the recurring "980px radius" in pill buttons echoes this width)
- Hero: full-viewport-width sections with centered content block
- Product grids: 2-3 column layouts within centered container
- Single-column for hero moments — one product, one message, full attention
- No visible grid lines or gutters — spacing creates implied structure

### Whitespace Philosophy
- **Cinematic breathing room**: Each product section occupies a full viewport height (or close to it). The whitespace between products is not empty — it is the pause between scenes in a film.
- **Vertical rhythm through color blocks**: Rather than using spacing alone to separate sections, Apple uses alternating background colors (black, `#f5f5f7`, white). Each color change signals a new "scene."
- **Compression within, expansion between**: Text blocks are tightly set (negative letter-spacing, tight line-heights) while the space surrounding them is vast. This creates a tension between density and openness.

### Border Radius Scale
- Micro (5px): Small containers, link tags
- Standard (8px): Buttons, product cards, image containers
- Comfortable (11px): Search inputs, filter buttons
- Large (12px): Feature panels, lifestyle image containers
- Full Pill (980px): CTA links ("Learn more", "Shop"), navigation pills
- Circle (50%): Media controls (play/pause, arrows)

## 6. Depth & Elevation

| Level | Treatment | Use |
|-------|-----------|-----|
| Flat (Level 0) | No shadow, solid background | Standard content sections, text blocks |
| Navigation Glass | `backdrop-filter: saturate(180%) blur(20px)` on `rgba(0,0,0,0.8)` | Sticky navigation bar — the glass effect |
| Subtle Lift (Level 1) | `rgba(0, 0, 0, 0.22) 3px 5px 30px 0px` | Product cards, floating elements |
| Media Control | `rgba(210, 210, 215, 0.64)` background with scale transforms | Play/pause buttons, carousel controls |
| Focus (Accessibility) | `2px solid #0071e3` outline | Keyboard focus on all interactive elements |

**Shadow Philosophy**: Apple uses shadow extremely sparingly. The primary shadow (`3px 5px 30px` with 0.22 opacity) is soft, wide, and offset — mimicking a diffused studio light casting a natural shadow beneath a physical object. This reinforces the "product as physical sculpture" metaphor. Most elements have NO shadow at all; elevation comes from background color contrast (dark card on darker background, or light card on slightly different gray).

### Decorative Depth
- Navigation glass: the translucent, blurred navigation bar is the most recognizable depth element, creating a sense of floating UI above scrolling content
- Section color transitions: depth is implied by the alternation between black and light gray sections rather than by shadows
- Product photography shadows: the products themselves cast shadows in their photography, so the UI doesn't need to add synthetic ones

## 7. Do's and Don'ts

### Do
- Use SF Pro Display at 20px+ and SF Pro Text below 20px — respect the optical sizing boundary
- Apply negative letter-spacing at all text sizes (not just headlines) — Apple tracks tight universally
- Use Apple Blue (`#0071e3`) ONLY for interactive elements — it must be the singular accent
- Alternate between black and light gray (`#f5f5f7`) section backgrounds for cinematic rhythm
- Use 980px pill radius for CTA links — the signature Apple link shape
- Keep product imagery on solid-color fields with no competing visual elements
- Use the translucent dark glass (`rgba(0,0,0,0.8)` + blur) for sticky navigation
- Compress headline line-heights to 1.07-1.14 — Apple headlines are famously tight

### Don't
- Don't introduce additional accent colors — the entire chromatic budget is spent on blue
- Don't use heavy shadows or multiple shadow layers — Apple's shadow system is one soft diffused shadow or nothing
- Don't use borders on cards or containers — Apple almost never uses visible borders (except on specific buttons)
- Don't apply wide letter-spacing to SF Pro — it is designed to run tight at every size
- Don't use weight 800 or 900 — the maximum is 700 (bold), and even that is rare
- Don't add textures, patterns, or gradients to backgrounds — solid colors only
- Don't make the navigation opaque — the glass blur effect is essential to the Apple UI identity
- Don't center-align body text — Apple body copy is left-aligned; only headlines center
- Don't use rounded corners larger than 12px on rectangular elements (980px is for pills only)

## 8. Responsive Behavior

### Breakpoints
| Name | Width | Key Changes |
|------|-------|-------------|
| Small Mobile | <360px | Minimum supported, single column |
| Mobile | 360-480px | Standard mobile layout |
| Mobile Large | 480-640px | Wider single column, larger images |
| Tablet Small | 640-834px | 2-column product grids begin |
| Tablet | 834-1024px | Full tablet layout, expanded nav |
| Desktop Small | 1024-1070px | Standard desktop layout begins |
| Desktop | 1070-1440px | Full layout, max content width |
| Large Desktop | >1440px | Centered with generous margins |

### Touch Targets
- Primary CTAs: 8px 15px padding creating ~44px touch height
- Navigation links: 48px height with adequate spacing
- Media controls: 50% radius circular buttons, minimum 44x44px
- "Learn more" pills: generous padding for comfortable tapping

### Collapsing Strategy
- Hero headlines: 56px Display → 40px → 28px on mobile, maintaining tight line-height proportionally
- Product grids: 3-column → 2-column → single column stacked
- Navigation: full horizontal nav → compact mobile menu (hamburger)
- Product hero modules: full-bleed maintained at all sizes, text scales down
- Section backgrounds: maintain full-width color blocks at all breakpoints — the cinematic rhythm never breaks
- Image sizing: products scale proportionally, never crop — the product silhouette is sacred

### Image Behavior
- Product photography maintains aspect ratio at all breakpoints
- Hero product images scale down but stay centered
- Full-bleed section backgrounds persist at every size
- Lifestyle images may crop on mobile but maintain their rounded corners
- Lazy loading for below-fold product images

## 9. Agent Prompt Guide

### Quick Color Reference
- Primary CTA: Apple Blue (`#0071e3`)
- Page background (light): `#f5f5f7`
- Page background (dark): `#000000`
- Heading text (light): `#1d1d1f`
- Heading text (dark): `#ffffff`
- Body text: `rgba(0, 0, 0, 0.8)` on light, `#ffffff` on dark
- Link (light bg): `#0066cc`
- Link (dark bg): `#2997ff`
- Focus ring: `#0071e3`
- Card shadow: `rgba(0, 0, 0, 0.22) 3px 5px 30px 0px`

### Example Component Prompts
- "Create a hero section on black background. Headline at 56px SF Pro Display weight 600, line-height 1.07, letter-spacing -0.28px, color white. One-line subtitle at 21px SF Pro Display weight 400, line-height 1.19, color white. Two pill CTAs: 'Learn more' (transparent bg, white text, 1px solid white border, 980px radius) and 'Buy' (Apple Blue #0071e3 bg, white text, 8px radius, 8px 15px padding)."
- "Design a product card: #f5f5f7 background, 8px border-radius, no border, no shadow. Product image top 60% of card on solid background. Title at 28px SF Pro Display weight 400, letter-spacing 0.196px, line-height 1.14. Description at 14px SF Pro Text weight 400, color rgba(0,0,0,0.8). 'Learn more' and 'Shop' links in #0066cc at 14px."
- "Build the Apple navigation: sticky, 48px height, background rgba(0,0,0,0.8) with backdrop-filter: saturate(180%) blur(20px). Links at 12px SF Pro Text weight 400, white text. Apple logo left, links centered, search and bag icons right."
- "Create an alternating section layout: first section black bg with white text and centered product image, second section #f5f5f7 bg with #1d1d1f text. Each section near full-viewport height with 56px headline and two pill CTAs below."
- "Design a 'Learn more' link: text #0066cc on light bg or #2997ff on dark bg, 14px SF Pro Text, underline on hover. After the text, include a right-arrow chevron character (>). Wrap in a container with 980px border-radius for pill shape when used as a standalone CTA."

### Iteration Guide
1. Every interactive element gets Apple Blue (`#0071e3`) — no other accent colors
2. Section backgrounds alternate: black for immersive moments, `#f5f5f7` for informational moments
3. Typography optical sizing: SF Pro Display at 20px+, SF Pro Text below — never mix
4. Negative letter-spacing at all sizes: -0.28px at 56px, -0.374px at 17px, -0.224px at 14px, -0.12px at 12px
5. The navigation glass effect (translucent dark + blur) is non-negotiable — it defines the Apple web experience
6. Products always appear on solid color fields — never on gradients, textures, or lifestyle backgrounds in hero modules
7. Shadow is rare and always soft: `3px 5px 30px 0.22 opacity` or nothing at all
8. Pill CTAs use 980px radius — this creates the signature Apple rounded-rectangle-that-looks-like-a-capsule shape

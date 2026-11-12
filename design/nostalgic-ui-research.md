# Nostalgic UI Research: Deal Intelligence & Sales Copilot

Status: draft for review · Date: 2026-11-12 · Scope: visual direction and design tokens only. No app code was changed.

Source key: **[F]** = fetched and read during this research. **[I]** = my inference or recommendation. **[K]** = my own knowledge, not checked against a fetched source. Hex values are my choices, modeled on the classic Windows palette. They are not copied from a fetched page.

---

## 1. Summary

- **Primary theme: "Classic Desk"**, an original take on the Windows 98-era "Classic" look: raised and sunken bevels, flat grey chrome, navy title bars, and white data fields.
- **Why:** the look is high-contrast by design, it separates panels with real borders instead of shadows and gradients, and it suits dense data (progress bars, list views, tabs, status bar). Black text on `#C0C0C0` gives 11.5:1 contrast, well above WCAG AA. **[I]**
- **Key tokens:** face `#C0C0C0`, field `#FFFFFF`, text `#000000`, select/title `#000080`, title gradient end `#0B3D91`, base font 12px `"Microsoft Sans Serif", Tahoma, Verdana, Arial, sans-serif`.
- **Name:** keep the product name. Do not use "Deal Desk 98" (see section 8).

---

## 2. References

| # | Source | What to borrow | Avoid / note |
|---|---|---|---|
| 1 | [98.css](https://jdan.github.io/98.css/) [F] | Bevel recipe; button sizes (75×23px, 12px padding); pressed, disabled, and focus states (dotted focus, 4px inset); fieldset as sunken outer + raised inner; title bar, status bar, tabs, sunken table, segmented progress | Its pixel-font look. MIT licensed, so keep the notice if the code is used. No JavaScript, so tabs and sorting need our own code. |
| 2 | [XP.css](https://botoxparty.github.io/XP.css/) [F] | `<progress>` markup; ARIA tab markup (`menu role="tablist"`, `aria-controls`, `role="tabpanel"`); the observation that it is a fork of 98.css | Luna (XP) theme. Not chosen. MIT. |
| 3 | [System.css](https://sakofchit.github.io/system.css/) [F] | `role="menu-bar"` markup; modal and alert double-outline frame; "details bar" under the title bar (useful for the deal header) | Mac System 6 monochrome look. Not chosen. |
| 4 | [Windows XP visual styles (Wikipedia)](https://en.wikipedia.org/wiki/Windows_XP_visual_styles) [F] | Contrast between "Windows Classic" (sharp bevels, 3D widgets) and Luna (rounded, glossy, green Start button). Notes that critics called Luna "childish". | Luna's rounded, glossy title bars and green Start button. |
| 5 | [Windows 98 (Wikipedia)](https://en.wikipedia.org/wiki/Windows_98) [F] | Two-colour gradient title bars; taskbar buttons for open windows; Back/Forward and address-bar navigation | Menu and tooltip slide animations. Drop them. |
| 6 | [Tahoma (Wikipedia)](https://en.wikipedia.org/wiki/Tahoma_(typeface)) [F] | Default UI face on Windows 2000 to XP; narrow body suits dense tables; uppercase I is distinct from lowercase l (useful for IDs); Wine ships a metric-compatible free replacement | Bold weight is heavy at small sizes. Keep it to labels and tables. |
| 7 | [Microsoft Sans Serif (Wikipedia)](https://en.wikipedia.org/wiki/Microsoft_Sans_Serif) [F] | Default system face on Win95/98/ME; TrueType, metric-compatible replacement for the bitmap original; bundled with macOS since Leopard | The original bitmap only looks right at its native sizes. Use the TrueType version. |
| 8 | [Webamp](https://github.com/captbaritone/webamp) [F] | Window chrome as inspiration (a "desktop app in the browser" feel) | README states Winamp's name, interface, and sample audio belong to Nullsoft. Do not copy its interface. Code is MIT. |
| 9 | [Frutiger Aero (Wikipedia)](https://en.wikipedia.org/wiki/Frutiger_Aero) [F] | Nostalgia context and the blue/green accent direction for small highlights | Glossy, reflective, bokeh and nature imagery, bright gradients. Not for data areas. |
| 10 | [Skeuomorph (Wikipedia)](https://en.wikipedia.org/wiki/Skeuomorph) [F] | Guardrails: skeuomorphs are "harder to operate", take "more screen space", and add "cognitive load" | Use bevels only where they carry meaning (panels, buttons, fields). |

**Attempted but not used:**

- `https://win98.js.org`: fetch returned no content.
- `https://98.js.org`: listed as a Windows 98 clone in the Webamp README [F], but my fetch returned only a few words, so I did not rely on it.
- Google search page: not fetched, as instructed.

---

## 3. Theme decision: why Windows 98 "Classic" over XP Luna or Frutiger Aero

| Criterion | Win98 Classic (chosen) | XP Luna | Frutiger Aero |
|---|---|---|---|
| Text contrast control | Solid flat colours; black on grey 11.5:1 [I] | Gradients and tinted chrome make contrast harder to guarantee [I] | Glossy, low-contrast highlights [I] |
| Panel separation for dense data | Bevels separate groupboxes, lists, and status bar | Rounded, softer edges; less crisp separation [I] | Decorative; competes with data [I] |
| Nostalgia fit | Strong for the target audience [I] | Recognisable, but critics called it "childish" [F] | Strong with Gen Z; reads as "2000s glossy" [F] |
| Effort to build | Small CSS token set and bevels | Gradients and radii, more fiddly to keep readable | Heavy effects, most work |
| Motion and effects | None needed | Gloss and gradients | Gloss, bokeh, and imagery |

**Recommendation:** Win98 Classic. It is the most readable option for a B2B data tool, and a dashboard that stays readable under density is more important than matching a period exactly. **[I]**

---

## 4. Design tokens

### 4.1 Palette

| Token | Hex | Use | Contrast (verified) |
|---|---|---|---|
| `--face` | `#C0C0C0` | Window body, buttons, panels | Base for text checks below |
| `--field` | `#FFFFFF` | Inputs, list views, tables, status fields | Base for text checks below |
| `--text` | `#000000` | Primary text | 11.5:1 on face; 21:1 on field |
| `--text-muted` | `#404040` | Secondary text, captions | 5.7:1 on face; 10.4:1 on field |
| `--edge-dark` | `#000000` | Outer bottom-right of raised | n/a (edge) |
| `--edge-mid` | `#808080` | Bevel shadow only, never text | 2.2:1 on face (edge only) |
| `--edge-light` | `#FFFFFF` | Bevel highlight | n/a (edge) |
| `--edge-soft` | `#DFDFDF` | Inner bevel highlight | n/a (edge) |
| `--edge-field` | `#404040` | Outer edge of sunken fields (see section 6) | 5.7:1 on face |
| `--select` | `#000080` | Selection, progress fill, active tab | White on it: 16:1 |
| `--title-start` | `#000080` | Title bar gradient start | White on it: 16:1 |
| `--title-end` | `#0B3D91` | Title bar gradient end | White on it: 10.0:1 |
| `--ok` | `#005000` | "Won", positive status (text on field only) | 9.8:1 on field |
| `--warn` | `#7A4B00` | Caution (text on field only) | 7.4:1 on field; **4.1:1 on face (fails)** |
| `--bad` | `#A00000` | Risk, "lost" (text on field only) | 8.4:1 on field |
| `--ok-fill` | `#005000` | Badge background with white text | White on it: 9.8:1 |
| `--bad-fill` | `#5A0000` | Badge background with white text | White on it: 14.6:1 |
| `--tooltip` | `#FFFFE1` | Tooltip background [K] | Black text well above 4.5:1 |

**Do not use:**

- `#1084D0` as title text colour. Classic title gradients end there, but white on it is 4.0:1, which fails 4.5:1 for small text. Use `#0B3D91` as the end stop.
- `#808080` as text on either grey or white (2.2:1 and 4.0:1; fails for text).
- `#006400` or `#7A4B00` as text on grey.

### 4.2 Font stack

```
--font-ui:   "Microsoft Sans Serif", Tahoma, Verdana, Arial, sans-serif;
--font-mono: "Courier New", Courier, monospace;
```

- `Microsoft Sans Serif` and `Tahoma` ship with Windows and, per the Wikipedia articles, with macOS. Verdana is a common Windows and Mac font, distributed with Tahoma in Office 97 [F for the Office 97 link; K for general availability]. Arial is a last-resort fallback for Linux [K].
- **Base size: 12px.** The classic 11px is small for dense tables on modern screens; WCAG sets no minimum font size, so this is a readability judgement. Headings: 14px bold. Title bar: 12px bold. **[I]**
- Use the mono stack only for raw IDs and JSON.

### 4.3 Bevel recipes

```css
.raised {                       /* buttons, window frame, groupbox inner */
  background: var(--face);
  box-shadow:
    inset -1px -1px var(--edge-dark),
    inset  1px  1px var(--edge-light),
    inset -2px -2px var(--edge-mid),
    inset  2px  2px var(--edge-soft);
}

.sunken {                       /* text fields, list views, status fields, pressed buttons */
  background: var(--field);
  box-shadow:
    inset  1px  1px var(--edge-field),
    inset -1px -1px var(--edge-light),
    inset  2px  2px var(--edge-mid),
    inset -2px -2px var(--edge-soft);
}
```

- The 98.css structure is followed: `fieldset` gets a sunken outer edge and a raised inner edge. The Microsoft UX text quoted in 98.css says field interiors use the button highlight colour (white) [F].
- Pressed buttons swap `.raised` for `.sunken` with `background: var(--face)`. Disabled buttons keep the raised edge with a washed-out label [F].

### 4.4 Title bar

```css
.title-bar {
  height: 20px;                 /* [I] classic range; tune to 12px font */
  padding: 0 2px;
  color: #FFFFFF;
  font-weight: 700;
  background: linear-gradient(90deg, var(--title-start), var(--title-end));
}
```

- Two-colour gradients in title bars date to Windows 98 [F].
- Title bar buttons are 16×14px raised squares with a glyph, labelled with `aria-label` (98.css pattern) [F].

### 4.5 Spacing and sizing

| Token | Value | Use |
|---|---|---|
| `--space-1` | 2px | Edge gaps, icon padding |
| `--space-2` | 4px | Between inline controls |
| `--space-3` | 8px | Groupbox padding, between field rows |
| `--space-4` | 12px | Window body padding |
| `--space-5` | 16px | Between groupboxes |
| `--space-6` | 24px | Section breaks |

- Buttons: min 75×23px, 12px horizontal padding (98.css defaults) [F].
- Window body: 8px padding. Groupbox: 8px inner padding plus a 12px label offset.
- Layout grid: 4px base, with 8px as the main rhythm **[I]**.

### 4.6 Focus

```css
button:focus-visible  { outline: 1px dotted #000; outline-offset: -4px; }   /* 98.css style, inset 4px [F] */
input:focus-visible,
[role="tab"]:focus-visible { outline: 2px solid #000; outline-offset: 1px; } /* stronger ring for fields and tabs [I] */
```

---

## 5. Component mapping

### 5.1 Wireframe (desktop, roughly 1100px wide)

```
+--[Deal DEAL-9042 - Qualification]----------------------[_][x]+
| File   View   Help                                            |   menu bar
| [ Deal DEAL-9042 > Qualification ]          (address field)   |   breadcrumb in sunken field
| +-- Qualification ----------------------+ +-- Estimates -----+ |
| | (PURSUE: HIGH PRIORITY) fit [####--] | | Win prob  68%    | |
| | 84 / 100                              | | [###-----]       | |
| | +-- BANT list (sunken) ------------+  | | Revenue $92,000  | |
| | | Factor    | Assessment           |  | | Timeframe 52 days| |
| | | Budget    | $80k-$100k confirmed |  | | Confidence HIGH  | |
| | +-----------------------------------+ | +------------------+ |
| +--------------------------------------+ +-- Effort ---------+ |
|                                          | Tier  Tier 1      | |
| [ Strategy ][ Risks ][ Analogues ]       | [ ] SA for POC    | |
| +-- tab content (window body) ---------+ | Max hours: 25     | |
| +----------------------------------------------------------+ |
| | Fit 84 | Win 68% | Confidence HIGH | Analogues: 3          | |  status bar
+-----------------------------------------------------------------+
```

- Stack panels in one column under 720px.
- Taskbar pattern (optional): one button per open deal, as Windows 98 did for windows [F]. Do not draw a Start button.

### 5.2 Section mapping

| Section (from schema) | Win98 component | Specific treatment |
|---|---|---|
| Window shell | `window` + `title-bar` | Title: "Deal DEAL-9042", with `deal_id` in mono. Only Minimise/Maximise/Close buttons are shown. Close is an icon button with `aria-label`. |
| Deal header | `details bar` (System.css pattern) [F] | Account name, stage, and `deal_id` in a sunken status strip under the title bar. |
| **Qualification** (`pursue_recommendation`, `fit_score`, `framework_breakdown`) | `fieldset` groupbox + segmented `progress-indicator` + sunken list view | Recommendation as a text badge (`.ok-fill`/`.warn-fill`), words included. Fit score as a segmented bar plus "84 / 100" text, so the number is never shown by the bar alone. BANT rows (Budget, Authority, Need, Timeline) in a sunken table with a 4-column layout. Selected row uses `--select`. |
| **Estimates** (`win_probability_pct`, `estimated_revenue_usd`, `estimated_timeframe_days`, `confidence_level`) | `fieldset` groupbox + solid `progress-indicator` + read-only `status-field-border` fields | Win probability as a solid bar with "68%" beside it. Revenue as a read-only sunken field, formatted as "$92,000 USD". Timeframe as "52 days". Confidence as a word badge: HIGH/MEDIUM/LOW. |
| **Effort allocation** (`tier`, `recommended_resources`, `max_recommended_hours`) | `fieldset` groupbox + `field-row` + checkboxes | Tier as a read-only sunken field. Each recommended resource as a checkbox. The checkbox state is UI-only (not in the schema), so label it that way. Max hours as a read-only numeric field. |
| **Closing playbook** (`winning_strategy`, `key_risks_and_mitigations`, `referenced_historical_deals`) | `menu role="tablist"` tabs with `tabpanel` | Three tabs: **Strategy** (plain paragraph in a window body), **Risks** (`tree-view`: risk as parent, mitigation as child), **Analogues** (see below). |
| **Historical analogues** (`referenced_historical_deals`, WON/LOST) | `table.interactive` inside `sunken-panel` | Columns: Deal ID (mono), Outcome (bold text badge: WON on `--ok-fill`, LOST on `--bad-fill`), Notes. Row click highlights in `--select`. Outcome is text, not colour alone. |
| Status bar | `status-bar` + `status-bar-field` | Fields: Fit score, Win %, Confidence, Analogues count. Use the status-field border (sunken outer only) [F]. |
| Tooltips | Plain tooltip, no animation | Pale yellow background (`--tooltip`), black text, appears instantly. |

---

## 6. Accessibility and readability

**Text contrast (WCAG 2.1 SC 1.4.3) [F]:** normal text needs 4.5:1, and large text (18pt, or 14pt bold, about 18.7px) needs 3:1. Ratios are not rounded, so 4.49:1 fails.

- Passing text pairs: black on face (11.5:1), black on white (21:1), `#404040` on face (5.7:1), white on `#000080` (16:1), white on `#0B3D91` (10.0:1).
- Failing text pairs to avoid: white on `#1084D0` (4.0:1), `#808080` on face (2.2:1), `#808080` on white (4.0:1, which fails only if used as text), `#7A4B00` on face (4.1:1).

**Non-text contrast and focus (SC 2.4.7 and 1.4.11) [F]:** focus indicators must be visible. Removing or hiding outlines is a documented failure (F78) [F]. The 98.css dotted focus is subtle, so section 4.6 adds a stronger ring for fields and tabs.

- Field boundary: `--edge-field` (`#404040`) is 5.7:1 against the face. The stock Win98 `#808080` edge is only 2.2:1, so it is deliberately darkened here [I].

**Motion [F]:** the reduced-motion preference is exposed through `prefers-reduced-motion: reduce` (MDN). Recommendations:

- No animated menus, tooltips, progress bars, or status pulses. This drops the Windows 98 slide animation [F].
- Ship no autoplay sounds (the Windows 98 startup and shutdown sounds are a nostalgia cue, but not in an app).
- If any transition is added later, wrap it in `@media (prefers-reduced-motion: no-preference)`.

**Colour is not the only signal:**

- Pursue, confidence, and WON/LOST always carry a word.
- The fit score and win % are always shown as numbers next to the bar.

**Sizing and reflow:**

- Base 12px, with headings at 14px. Use `rem` or `%` widths so the layout can zoom and reflow. Avoid fixed-width windows in the app itself (98.css examples use fixed widths for demos) [F].
- Keep tap and click targets at least 23px high, matching the classic button size [F].

**Screen readers and keyboard:**

- Title bar buttons use `aria-label` (98.css pattern) [F].
- Tabs follow the ARIA tab pattern (`role="tablist"`, `role="tab"`, `aria-selected`, `role="tabpanel"`), as in the XP.css docs [F]. Arrow keys move between tabs; Tab moves into the panel.
- `fieldset` plus `legend` for each groupbox, so screen readers announce section names.

---

## 7. Do-not list

1. **No Microsoft or Windows branding.** Do not use the Windows logo, flag, "Start" orb, green Start button, Bliss or other Microsoft wallpapers, icons, or system sounds [K for the logo and sounds; F for the Start button and Bliss as Windows XP features].
2. **No Microsoft product names in the UI, copy, or domain.** Avoid "Windows", "Win98", "XP", "Luna", "Aero", and "Frutiger". Do not imply that Microsoft endorses or sponsors the product. For naming, the trademark guidance is to use names as adjectives alongside a generic term, and to run a clearance search before launch [F].
3. **No Winamp or Webamp assets or interface.** Their README says the Winamp name, interface, and sample audio are Nullsoft's [F].
4. **No Frutiger Aero effects in data areas.** No gloss, bokeh, reflective highlights, or nature imagery behind tables or scores [I].
5. **No grey text on grey.** Text is `#000` or `#404040` on face, `#000` on field. Keep `#808080` for bevel edges only [I].
6. **No animated chrome.** No slide-in menus, bouncing progress, flashing status, or sound effects [F for the Windows 98 animations; I for the recommendation].
7. **No colour-only status.** Every badge and bar has text beside it [I].
8. **No more than two bevel levels inside a panel.** Nested raised and sunken layers add visual noise, which the skeuomorph critique warns about [F].
9. **No pixel fonts or bitmap MS Sans Serif for body text.** Use the TrueType versions in the font stack [F].
10. **No claim of an authentic Windows 98 replica** in marketing or docs. This is a "Classic" look inspired by the period [I].

---

## 8. Naming note

- **Keep the product name** "Deal Intelligence & Sales Copilot".
- **Theme name:** "Classic Desk" (internal only).
- **Do not use "Deal Desk 98".** The "98" points directly at Windows 98, so it reads as affiliated. It is a judgement call, not a legal opinion [I].
- If a new product name is wanted, run a trademark clearance search first [F].

---

## 9. Open questions and next steps

1. **Ship 98.css or hand-roll tokens?** 98.css is MIT and gives the bevels, title bar, tabs, and progress bar out of the box. If used, keep its copyright notice [F]. Hand-rolling keeps control of the contrast fixes in section 4 [I].
2. **Framework fit.** The build guide offers Next.js with Tailwind or Streamlit [F]. Streamlit makes bevelled widgets hard to style [I], so Next.js or plain HTML/CSS suits this theme better. Confirm before building.
3. **Font availability.** Verify Microsoft Sans Serif and Tahoma on the target machines. On Linux, the stack falls back to Verdana or Arial, so check the layout there [I].
4. **Hex values.** I have not verified the exact classic palette against a Win98 screenshot. Verify visually before locking tokens [I].
5. **Legal review** if the product ships commercially and the look is close to Windows 98 [I].
6. **Usability check.** Test with 3 to 5 sales reps: can they find the recommendation, the win %, and the top analogue within a few seconds, at 12px?

---

*Sources read: 98.css, XP.css, System.css, Webamp README, Windows XP visual styles, Windows 98, Tahoma, Microsoft Sans Serif, Trademark, Frutiger Aero, Skeuomorph (Wikipedia), W3C WCAG 2.1 Understanding SC 1.4.3 and SC 2.4.7, MDN prefers-reduced-motion. Build guide: `RAGs2Riches/deal_intelligence_engine_build_guide.md`.*

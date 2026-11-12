# Addendum: Portal-era direction ("Portal 2000")

Date: 2026-11-12. This supersedes the theme choice in `nostalgic-ui-research.md` sections 3-5 (Win98 window chrome). Sections 6-7 (accessibility, do-not list) still apply. The research doc's contrast and focus rules stay in force.

Source key: **[S]** = seen in the user's reference screenshots. **[I]** = my inference or recommendation. **[K]** = my own knowledge, not fetched. The screenshots were provided by the user. Contrast ratios were computed with the WCAG formula.

## 1. What the references show

| Reference | Observed [S] | Borrow |
|---|---|---|
| Cartoon Network portal | Dark nav bar with pill arrows; angled coloured top tabs; saturated blue gradient panels; one large featured banner; "What's on now" time list in the left rail; ad boxes with thick dark borders in a right rail | Featured hero box; compact time-list pattern for key facts; thick-bordered side boxes |
| Miniclip | Dense mid-blue page; white boxes with coloured header strips (orange "TOP TEN", blue category headers with small icon); featured box with one orange "PLAY NOW" button; square-bullet link lists; "List all..." orange links; 3-column layout | Header-strip boxes; ranked top-N list; single orange call-to-action; square bullets |
| Neopets | Yellow rounded sidebar with large icon+label navigation; heavy black outer frame; playful display wordmark; thin divider rules between sections; small dark body text on cream; poll with radio buttons | Left rail as a framed panel; divider rules; cream info boxes |
| WarpStream (IE6) | Real browser chrome; black nav strip with white labels; white content area; blue underlined links; tag cloud; star rating; spec table (Views / Comments) | Black nav strip; underlined links; label-value spec blocks; small tag chips |

Shared traits [I]: 3-zone layout (left rail, centre feature, right rail), boxes with a coloured header strip, thick borders, saturated primaries on a blue page, one orange/yellow accent for the main action, Verdana-class text at 11-12px, bold display type only for headings and wordmarks.

## 2. Layout and visual hierarchy

```
+----------------------------------------------------------------+
| [WORDMARK]            [Deal Desk][Analogues][Playbook]  search? |  dark nav strip (#0b1f3a)
+----------------------------------------------------------------+
| LEFT RAIL (cream)  |  FEATURED (hero)              | RIGHT RAIL |
|  NEW DEAL form     |  Account / DEAL-ID            |  TOP 5     |
|  (framed box,      |  [PURSUE HIGH PRIORITY]       |  ANALOGUES |
|   yellow header)   |  Fit 84/100  Win 68%          |  (ranked,  |
|  [EVALUATE] orange |  Expected $92,000  52 days    |   WON/LOST |
|                    +-------------------------------+   text)    |
|                    | Qualification | Estimates     |            |
|                    | Effort        | Playbook tabs |  quick     |
|                    |                               |  facts     |
+----------------------------------------------------------------+
| footer: sample data notice, version                             |
+----------------------------------------------------------------+
```

Reading order and weight (strongest first) [I]:
1. Featured hero: recommendation badge (largest type, 20px display font), then fit score and win probability as big numerals (28px) with segmented bars.
2. The single orange EVALUATE button (the only orange filled button on screen).
3. Four category boxes (Qualification, Estimates, Effort, Playbook), equal size, 2x2 grid, each with a header strip.
4. Right rail: top 5 analogues as a ranked list.
5. Footer and hints (smallest, muted).

Balance: left rail 300px, right rail 240px, centre fluid. Under 960px the right rail moves below the centre; under 640px everything is one column, with the form first. Equal 12px gutters. Boxes in the same row share equal heights.

## 3. Palette (contrast computed)

| Token | Hex | Use | Contrast |
|---|---|---|---|
| `--page` | `#2b66b1` | Page background | Only decoration; no text on it except via boxes |
| `--page-dark` | `#15386b` | Footer, outer frame | White text 11.6:1 |
| `--nav` | `#0b1f3a` | Nav strip | Yellow `#ffd84a` text 11.9:1; white 16.5:1 |
| `--panel` | `#eaf3ff` | Rail and box bodies | `#0b1f3a` text 14.8:1 |
| `--box` | `#ffffff` | Data surfaces | `#0b1f3a` text 16.5:1 |
| `--ink` | `#0b1f3a` | Primary text | see above |
| `--ink-muted` | `#3a4a63` | Secondary text | 9.0:1 on white, 8.0:1 on panel |
| `--header-blue` | `#123f7f` | Box header strip | White text 10.3:1 |
| `--header-orange` | `#ffa11a` | Accent header strip, primary button | `#0b1f3a` text 8.2:1 |
| `--header-yellow` | `#ffd84a` | Form header strip, highlights | `#0b1f3a` text 11.9:1 |
| `--link` | `#0a4fb3` | Links | 7.6:1 on white, 6.7:1 on panel |
| `--ok` | `#1c6b1c` | WON, positive badge fill (white text) | 6.6:1 |
| `--bad` | `#a31414` | LOST, negative badge fill (white text) | 7.9:1 |
| `--warn-fill` | `#ffa11a` | "QUALIFY FURTHER" badge: orange fill with `--ink` text (never white) | 8.2:1 |
| `--note` | `#fff6bf` | Hint and sample-data notes | `#0b1f3a` 15.1:1 |

Avoid: yellow `#ffd84a` text on `#2b66b1` (4.2:1, fails); orange `#d98200` text on white (2.9:1, fails); any white text on `#ffa11a`.

## 4. Typography

| Role | Stack | Size / weight | Reason |
|---|---|---|---|
| Body, forms, tables | `Verdana, Tahoma, Geneva, sans-serif` | 12px / 400, line-height 1.45 | Period-correct for portal sites in the screenshots; Verdana is wide with open spacing, which stays readable at small sizes [K] |
| Box headers, nav labels | `"Trebuchet MS", Verdana, sans-serif` | 13px / 700, uppercase, letter-spacing 0.04em | Friendly, slightly rounded humanist sans that matches the playful headers [K] |
| Wordmark, hero numerals | `"Arial Black", Impact, "Trebuchet MS", sans-serif` | 20-28px / 900 | Heavy display face echoing the Miniclip and Neopets wordmarks [I] |
| IDs, raw values | `"Courier New", monospace` | 12px | Unchanged |

All of these ship with Windows and macOS [K]. No web fonts, no downloads, so the .exe stays offline. Do not use Comic Sans (it clashes with a B2B tool) or pixel fonts.

## 5. Component rules

- **Box:** 2px solid `--ink` border, 6px radius on the outer corners, header strip 26px tall (blue, orange or yellow), body `--panel` or `--box`. Soft hard-edge shadow `3px 3px 0 rgba(11,31,58,.35)` (no blur).
- **Nav strip:** `--nav` background, white or yellow labels, active item gets a yellow underline 3px plus bold (not colour alone). Angled tabs are optional (CSS `clip-path`/skew); keep text unskewed.
- **Primary button (EVALUATE):** orange `#ffa11a`, 2px `--ink` border, 6px radius, dark text 13px bold uppercase, hover `#ffb84d`, pressed shifts 1px. Secondary buttons: white with ink border.
- **Inputs:** white, 2px `#3a4a63` border, 3px radius, 26px min height, focus = 3px solid `#0a4fb3` outline offset 1px plus keep the browser default fallback.
- **Progress bars:** 18px tall, white track with 2px ink border, segmented fill (`--header-blue`), number always printed beside.
- **Badges:** text always present. WON green fill, LOST red fill, PURSUE green, QUALIFY FURTHER orange with dark text, DEPRIORITIZE red.
- **Lists:** square bullets (`list-style: square`) with `--link` colour; underlined links; "List all..." style links in dark orange are NOT allowed as text (contrast), use `--link`.
- **Dividers:** 1px dashed `#8fb1d9` between sections inside boxes (Neopets-style rules).
- **Chips:** small tag chips (WarpStream tags) for industry, size tier, stage: white, 1px ink border, 2px radius.
- **Motion:** none required. If hover transitions are added, wrap in `prefers-reduced-motion: no-preference`.

## 6. Do-not list (additions)

1. No Cartoon Network, Miniclip, Neopets, WarpStream, Cartoon-style characters, logos, mascots, wordmarks, or copied artwork. Take structure, colour mood, and type feel only.
2. No Flash-style intros, marquee, blink, auto-playing sound, or ad banners. Flash banner nags ("Flash Player required") must not be imitated as fake warnings.
3. No colour-only status; no white text on orange; no yellow text on mid-blue.
4. No more than one filled orange button per screen.
5. No fake "visitor counter" or "under construction" gimmicks.

## 6b. Motion and feedback (added at the user's request; overrides "no animated chrome" in the research doc)

All motion sits behind `prefers-reduced-motion: no-preference`. With reduced motion, values appear instantly, the loading steps complete at once, and no animation runs (checked in headless Chrome: 0 running animations).

| Moment | Feedback |
|---|---|
| Page load | Boxes rise in with a stagger; wordmark bars grow; Evaluate button pulses until first use |
| Hover / press | Buttons lift with a hard shadow, then sink on press; ripple from the pointer; tabs and ranked rows nudge |
| Typing | Tick beside each valid field; live character counter for notes |
| Invalid submit | Fields shake, first invalid field focused, error toast |
| Evaluating | Three-step stepper (baseline, analogues, scorecard) with an indeterminate bar; old results dim |
| Result | Staggered box entrance; numbers count up; bars fill from empty; badge pops; confetti only for PURSUE HIGH PRIORITY |
| Analogue selected | Row and rail item flash; detail pane fades in |
| Checklist | Strikethrough, "n of m steps done", success toast when complete |
| Copy summary | Button turns green with a tick, toast, status line |
| Sound | Opt-in toggle in the nav, off by default, synthesised tones, saved in localStorage |

Toasts are `aria-hidden` because the status line announces the same text. Every cue also has a non-motion form (text, tick or label).

## 7. Open questions

1. Keep the nav strip decorative (single "Deal Desk" view) or wire it to the three views? Recommendation: single view for now, with items acting as anchors [I].
2. Confirm hex values visually in a browser; only the contrast was computed.

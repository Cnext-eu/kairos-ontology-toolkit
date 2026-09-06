# Power BI report design — inspiration, not a gate

**Nothing here is validated by the toolkit, and nothing here blocks an emit.** The hub
governs the semantic model: tables, relationships, measures, calendar, security, column
visibility. Everything on this page is about the *report*, which belongs to whoever builds
it. Use it when shaping insights with a client and when briefing a BI engineer. Drop any
item that does not fit the client in front of you — a rule you cannot justify to them is
not a rule worth keeping.

## What the platform already gives you

**Native visuals and the formatting pane** cover roughly 80% of real reporting needs. The
parts teams consistently underuse:

- report page tooltips, and drillthrough
- bookmarks with the selection pane, for switching state instead of adding pages
- small multiples
- field parameters, letting users swap measures or dimensions without extra pages
- conditional formatting driven by a DAX measure
- the new card visual

**Theme and layout files** are the highest-leverage consistency tool, and most teams skip
them. A JSON theme locks fonts, palette, padding and per-visual defaults across every
report. Pair it with a `.pbit` template so new reports start from the standard. Backgrounds
designed in Figma or PowerPoint and exported as PNG at 1280×720 or 1920×1080 give you a
real grid, headers and card containers.

## UX practices that change outcomes

- **Start from the decision, not the data.** Ask what someone will do differently after
  reading this page. If there is no answer, the page should not exist. This is the same
  discipline `insights.yaml` records: a persona, a question, and the KPI that answers it.
- **One page, one message.** Five to eight visuals. Put overview, filtered view and detail
  on separate layers — drillthrough and tooltips — rather than all at once.
- **Top-left is the most expensive real estate.** Eyes scan in a Z or F pattern. Headline
  number top-left, supporting detail lower right.
- **Titles as takeaways.** "Revenue fell 8% in Q3, driven by Benelux" beats "Revenue by
  Quarter". This is the cheapest insight upgrade available.
- **Colour is a signal, not decoration.** Grey by default; colour only where you want the
  eye to go. Never encode meaning in colour alone — around 8% of men cannot distinguish red
  from green. Check contrast at 4.5:1.
- **Align and space on a grid.** Misalignment reads as sloppiness even when a viewer cannot
  say why.
- **Accessibility is not optional in most enterprises.** Set tab order, add alt text, keep
  keyboard navigation working, and run the built-in accessibility checker.
- **Performance is UX.** Anything over about five seconds to load erodes trust. Run
  Performance Analyzer before shipping.
- **Wireframe before building.** Twenty minutes on paper or in Figma saves a week of
  rework, and stakeholders will happily critique a sketch while they feel obliged to approve
  something that looks finished.

## For the insight side

- **IBCS (the SUCCESS rules)** is a genuine standard for business reporting notation:
  consistent treatment of actual versus plan versus prior year, variance bars, scaling.
  Worth reading even if you adopt half of it.
- **Every number needs a comparison.** A KPI alone is noise; against a target, a prior
  period or a benchmark it becomes information. This is why an insight carries a
  `comparison` field.
- **Books that hold up:** Cole Nussbaumer Knaflic, *Storytelling with Data* (start here);
  Stephen Few, *Information Dashboard Design*; Alberto Cairo, *The Truthful Art*.
- **Power BI's own analytical visuals** — key influencers, decomposition tree, anomaly
  detection, smart narrative — are underrated for exploratory pages, but they need
  supervision before they go in front of executives.

## Where the hub's boundary is

The hub emits a semantic model and a stub report item. Build the real report as a
**separate Fabric item with its own name**, bound to the deployed model. The generated
`<Product>.Report` is republished on every hub release, so edits to it are lost.

If a report needs something the model does not have — a measure, a column, a relationship —
that is a hub change: author it, or run `harvest-gold` to turn what you built in Desktop
into a proposal. Do not work around the model in the report layer; that is how a governed
measure quietly acquires three competing definitions.

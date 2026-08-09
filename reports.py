"""Report generation.

Phase 1b ships a deterministic stub: no LLM, no network, no randomness, so
the same purchase always yields the same report. Phase 2 replaces the body
copy with model output — `generate_report`'s signature stays as-is.
"""

import json
import logging

import config
import database

log = logging.getLogger(__name__)

INSERT_SQL = "INSERT INTO reports (purchase_id, content) VALUES (%s, %s)"

# Body templates keyed by section id. Each renders 3-5 sentences and names the
# style so the stub reads as belonging to this specific result.
BODIES = {
    "palette": (
        "Your {name} palette leans on three colors that showed up again and "
        "again in the rooms you picked. The base carries the walls and the "
        "bulk of the cabinetry, so it stays quiet on purpose. The second "
        "color does the work on the island and the joinery. The accent is "
        "the one you use sparingly — hardware, a stool, a single wall. "
        "Placeholder copy: exact paint and finish codes arrive in Phase 2."
    ),
    "mistakes": (
        "Every {name} kitchen goes wrong in roughly the same five places. "
        "The expensive one is committing to a finish before seeing it under "
        "your own light. The common one is matching everything, which flattens "
        "the room instead of calming it. The third is buying the statement "
        "piece first and building around it. Placeholder copy: the full five, "
        "with fixes, arrive in Phase 2."
    ),
    "materials": (
        "{name} rooms live or die on the worktop, and yours has two sensible "
        "options and one that only looks right in photographs. Pair the "
        "counter with a splashback that shares its undertone rather than its "
        "color. Keep metals to two finishes at most across the whole room. "
        "Placeholder copy: the full material matrix arrives in Phase 2."
    ),
    "shopping": (
        "Three pieces carry a {name} kitchen, and the rest is supporting cast. "
        "Buy the lighting and the hardware first — they change the room "
        "immediately and cost the least to get right. Leave the seating until "
        "the cabinetry is in, because proportions shift once it lands. "
        "Placeholder copy: the itemized list arrives in Phase 2."
    ),
    "dna": (
        "Your answers read as {name}, but not purely — no one's ever do. "
        "There is a clear secondary influence sitting underneath your picks, "
        "showing up in the textures you kept choosing. The tension between "
        "the two is what will make the room look considered rather than "
        "copied. Placeholder copy: the full breakdown arrives in Phase 2."
    ),
    "splurge": (
        "In a {name} kitchen exactly one line item rewards overspending, and "
        "it is not the appliances. Everything touched daily deserves the "
        "budget; everything looked at deserves the cheaper version done well. "
        "The savings usually come from cabinetry carcasses, where nobody can "
        "tell the difference. Placeholder copy: the budget split arrives in "
        "Phase 2."
    ),
}

GENERIC_BODY = (
    "Placeholder copy for your {name} result. This section is generated as a "
    "stub in Phase 1b so the end-to-end purchase flow can be tested with real "
    "Stripe events. The structure, ordering and section titles are final. "
    "Only the body text is replaced in Phase 2."
)


def _style_name(cfg, result_style):
    """Human name for a style id, falling back to the id itself."""
    for style in cfg.get("styles", []):
        if style.get("id") == result_style:
            return style.get("name") or style.get("id")
    return result_style or "your style"


def generate_report(purchase_id, funnel_slug, result_style):
    """Build and persist the report for a purchase. Returns the content dict.

    Raises if the funnel config is missing or the INSERT fails — callers
    decide whether that is fatal (for the webhook, it is not).
    """
    cfg = config.load_funnel(funnel_slug)
    name = _style_name(cfg, result_style)

    sections = []
    for section in cfg.get("report", {}).get("sections", []):
        if section.get("enabled") is False:
            continue
        template = BODIES.get(section.get("id"), GENERIC_BODY)
        sections.append(
            {
                "id": section.get("id"),
                "title": section.get("title"),
                "body": template.format(name=name),
            }
        )

    content = {
        "version": "stub-1",
        "funnel": funnel_slug,
        "style_id": result_style,
        "style_name": name,
        "sections": sections,
    }

    database.execute(
        INSERT_SQL, (purchase_id, json.dumps(content, separators=(",", ":")))
    )
    log.info("report generated for purchase %s (%d sections)", purchase_id, len(sections))
    return content

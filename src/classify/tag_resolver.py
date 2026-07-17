"""
Stage F — Tag resolution.

Takes candidate tags from all upstream stages (A–E) and produces the
final set of tags for each file:

1. Filter by enabled categories (from wizard config)
2. Apply confidence threshold (auto vs needs-review)
3. Resolve conflicts via priority table (lower number wins as primary)
4. Assign fallback ``other`` tag if no tags were assigned
5. Write final tags to the database
"""

from __future__ import annotations

from src.classify import db


def resolve_tags(
    file_id: int,
    candidate_tags: dict[str, tuple[float, str]],
    enabled_categories: set[str],
    auto_threshold: float,
    run_id: str | None = None,
) -> list[dict]:
    """
    Resolve candidate tags into final tags and write them to the database.

    Args:
        file_id: The media file database ID.
        candidate_tags: ``{category_key: (confidence, source)}`` from stages A–E.
        enabled_categories: Set of category keys toggled on in the wizard.
        auto_threshold: Minimum confidence for auto-classification.
            Tags below this go to the review queue.
        run_id: The classify job run ID.

    Returns:
        List of dicts describing final tags written.
    """
    categories = {c["key"]: c for c in db.get_categories()}
    final_tags: list[dict] = []
    review_items: list[dict] = []

    for cat_key, (confidence, source) in candidate_tags.items():
        # Skip disabled categories
        if cat_key not in enabled_categories:
            continue

        cat_info = categories.get(cat_key)
        if cat_info is None:
            continue

        if confidence >= auto_threshold:
            # Auto-apply tag
            db.add_tag(file_id, cat_key, confidence, source, run_id)
            final_tags.append(
                {
                    "category": cat_key,
                    "label": cat_info["label"],
                    "confidence": confidence,
                    "source": source,
                    "status": "auto",
                }
            )
        else:
            # Send to review queue
            db.add_to_review_queue(
                file_id,
                review_type=_source_to_review_type(source),
                suggested_category_id=cat_info["id"],
                confidence=confidence,
                run_id=run_id,
            )
            review_items.append(
                {
                    "category": cat_key,
                    "label": cat_info["label"],
                    "confidence": confidence,
                    "source": source,
                    "status": "review",
                }
            )

    # Fallback: if no tags were auto-applied, assign "other"
    if not final_tags and "other" in enabled_categories:
        db.add_tag(file_id, "other", 1.0, "fallback", run_id)
        other_info = categories.get("other", {})
        final_tags.append(
            {
                "category": "other",
                "label": other_info.get("label", "Other / Unclassified"),
                "confidence": 1.0,
                "source": "fallback",
                "status": "auto",
            }
        )

    return final_tags + review_items


def _source_to_review_type(source: str) -> str:
    """Map a tag source to a review queue type."""
    if source in ("ml_scene",):
        return "scene"
    if source in ("ml_face", "face_bbox", "face+scene", "face+exif"):
        return "face"
    if source in ("heuristic",):
        return "document"
    return "scene"

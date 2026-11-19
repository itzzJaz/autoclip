"""Metadata drafts for a published clip.

The model is constrained to facts in the clip's own title, hook, and transcript.
When no provider is reachable the module still returns an editable draft built
only from that same text — clearly marked as a local draft — rather than
inventing a description or failing the publish screen outright.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from ..config import PublishSettings
from ..config import load as load_settings
from ..providers import build_provider
from ..providers.base import DetectionConfig, extract_json_object

log = logging.getLogger(__name__)

_MAX_TITLE = 100
_MAX_DESCRIPTION = 5000
_MAX_TAG_CHARS = 500

_STYLE_NOTES = {
    "concise": "Two or three sentences. Lead with the moment, no throat-clearing.",
    "story": "A short narrative arc: the setup, the turn, and why it matters.",
    "educational": "Explain the idea plainly and end with one concrete takeaway.",
}


class _MetadataPayload(BaseModel):
    titles: list[str] = Field(default_factory=list)
    recommended_title: str = ""
    description: str = ""
    hashtags: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


@dataclass
class GeneratedMetadata:
    titles: list[str]
    recommended_title: str
    description: str
    hashtags: list[str]
    tags: list[str]
    generated_by: str = "provider"
    warning: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class ClipContext:
    title: str
    hook: str
    reason: str
    transcript: str
    duration_s: float
    source_title: str = ""


async def generate(
    context: ClipContext, settings: PublishSettings | None = None
) -> GeneratedMetadata:
    settings = settings or load_settings().publish
    defaults = _split_list(settings.default_hashtags)

    try:
        provider = build_provider()
        raw = await provider.complete_text(
            _system_prompt(settings),
            _user_prompt(context, settings),
            DetectionConfig(temperature=0.6),
        )
        payload = _MetadataPayload.model_validate(extract_json_object(raw))
        metadata = _normalise(payload, context, settings, defaults)
        metadata.generated_by = provider.name
        return metadata
    except Exception as exc:  # noqa: BLE001 - every provider can fail
        log.warning("Metadata generation fell back to local text: %s", exc)
        return _fallback(context, settings, defaults, str(exc))


def _system_prompt(settings: PublishSettings) -> str:
    hashtag_rule = (
        "Include the hashtags at the end of the description as well."
        if settings.hashtags_in_description
        else "Do not put hashtags in the description; they go in the hashtags field only."
    )
    return (
        "You write metadata for a YouTube Short. Use ONLY facts present in the supplied "
        "clip title, hook, rationale, and transcript. Never invent events, quotes, numbers, "
        "names, or outcomes. No false clickbait. Titles must be under 100 characters.\n\n"
        "Description style: "
        f"{_STYLE_NOTES.get(settings.description_style, _STYLE_NOTES['concise'])}\n"
        f"{hashtag_rule}\n"
        "Give 3 distinct title options and choose the strongest as recommended_title. "
        "Give 3 to 5 hashtags, each starting with # and containing no spaces. "
        "Give 5 to 10 short tags without #.\n"
        "Do not add #Shorts unless it is already present in the supplied saved hashtags.\n\n"
        "Return ONLY a JSON object with keys: titles (array of 3 strings), "
        "recommended_title (string), description (string), hashtags (array), tags (array). "
        "No markdown fences, no prose."
    )


def _user_prompt(context: ClipContext, settings: PublishSettings) -> str:
    transcript = context.transcript.strip()
    if len(transcript) > 6000:
        transcript = transcript[:6000] + " …"
    saved = ", ".join(_split_list(settings.default_hashtags)) or "(none)"
    return (
        f"Source video: {context.source_title or 'untitled'}\n"
        f"Clip title: {context.title or '(none)'}\n"
        f"Hook: {context.hook or '(none)'}\n"
        f"Why this clip was chosen: {context.reason or '(none)'}\n"
        f"Clip duration: {context.duration_s:.1f} seconds\n"
        f"Saved hashtags to keep if relevant: {saved}\n\n"
        f"Transcript:\n{transcript or '(no transcript available)'}\n"
    )


def _normalise(
    payload: _MetadataPayload,
    context: ClipContext,
    settings: PublishSettings,
    defaults: list[str],
) -> GeneratedMetadata:
    notes: list[str] = []

    titles = _unique([_clean_title(title) for title in payload.titles if title.strip()])
    if len(titles) < 3:
        for candidate in (context.title, context.hook):
            cleaned = _clean_title(candidate)
            if cleaned and cleaned not in titles:
                titles.append(cleaned)
            if len(titles) >= 3:
                break
    if not titles:
        titles = [_clean_title(context.title) or "Untitled clip"]
        notes.append("The provider returned no usable titles.")

    recommended = _clean_title(payload.recommended_title)
    if recommended not in titles:
        recommended = titles[0]

    description = _clean_description(payload.description)
    if not description:
        description = _clean_description(context.hook or context.title)
        notes.append("The provider returned no description; the clip hook was used.")

    hashtags = _clean_hashtags(payload.hashtags, defaults)
    if len(hashtags) < 3:
        hashtags = _clean_hashtags([], [*hashtags, *defaults, *_keywords(context)])
    if len(hashtags) < 3:
        notes.append("Fewer than three hashtags were available; add one before publishing.")

    tags = _clean_tags([*payload.tags, *(_split_list(settings.default_tags))])

    if (
        settings.hashtags_in_description
        and hashtags
        and not all(tag in description for tag in hashtags)
    ):
        suffix = " ".join(hashtags)
        if len(description) + len(suffix) + 2 <= _MAX_DESCRIPTION:
            description = f"{description.rstrip()}\n\n{suffix}"

    return GeneratedMetadata(
        titles=titles[:3],
        recommended_title=recommended,
        description=description,
        hashtags=hashtags[:5],
        tags=tags,
        notes=notes,
    )


def _fallback(
    context: ClipContext,
    settings: PublishSettings,
    defaults: list[str],
    error: str,
) -> GeneratedMetadata:
    base = _clean_title(context.title) or _clean_title(context.hook) or "Untitled clip"
    hook = _clean_title(context.hook)
    titles = _unique([base, f"{base} — the moment", hook or base])
    if len(titles) < 3:
        titles.append(f"{base} (clip)")

    description = _clean_description(context.hook) or base
    if context.reason and context.reason not in description:
        description = f"{description.rstrip()}\n\n{context.reason.strip()}"

    hashtags = _clean_hashtags(defaults, _keywords(context))[:5]
    if len(hashtags) < 3:
        hashtags = _clean_hashtags([], [*hashtags, "#clip", "#video"])[:5]

    if settings.hashtags_in_description and hashtags:
        description = f"{description.rstrip()}\n\n{' '.join(hashtags)}"

    return GeneratedMetadata(
        titles=titles[:3],
        recommended_title=titles[0],
        description=_clean_description(description),
        hashtags=hashtags,
        tags=_clean_tags(_split_list(settings.default_tags)),
        generated_by="local-draft",
        warning=(
            "No AI provider answered, so this draft was assembled only from the clip title "
            "and hook. Edit it before publishing."
        ),
        notes=[error[:300]],
    )


# --------------------------------------------------------------------------
# Sanitisers
# --------------------------------------------------------------------------


def _clean_title(value: str) -> str:
    text = re.sub(r"\s+", " ", (value or "").strip()).strip("\"' ")
    if len(text) > _MAX_TITLE:
        text = text[: _MAX_TITLE - 1].rstrip() + "…"
    return text


def _clean_description(value: str) -> str:
    text = (value or "").strip()
    if len(text) > _MAX_DESCRIPTION:
        text = text[: _MAX_DESCRIPTION - 1].rstrip() + "…"
    return text


def _clean_hashtags(values: list[str], defaults: list[str]) -> list[str]:
    seen: list[str] = []
    for source_index, source in enumerate((values, defaults)):
        for raw in source:
            for piece in re.split(r"[,]+", raw or ""):
                piece = piece.strip()
                if not piece:
                    continue
                if re.search(r"\s", piece):
                    piece = piece.split()[0]
                tag = piece.lstrip("#")
                tag = re.sub(r"[^\w]", "", tag, flags=re.UNICODE)
                if not tag:
                    continue
                if source_index == 1 or not piece.startswith("#"):
                    tag = tag.lower()
                candidate = f"#{tag}"
                if candidate.lower() not in {item.lower() for item in seen}:
                    seen.append(candidate)
    return seen


def _clean_tags(values: list[str]) -> list[str]:
    tags: list[str] = []
    total = 0
    for raw in values:
        for piece in re.split(r"[,\n]+", raw or ""):
            tag = re.sub(r"\s+", " ", piece).strip().lstrip("#")
            if not tag or tag.lower() in {item.lower() for item in tags}:
                continue
            if total + len(tag) + 1 > _MAX_TAG_CHARS:
                return tags
            tags.append(tag)
            total += len(tag) + 1
    return tags


def _keywords(context: ClipContext) -> list[str]:
    """Safe hashtags derived only from the clip's own words."""
    text = f"{context.title} {context.hook}"
    words = [
        word
        for word in re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", text)
        if word.lower() not in _STOP_WORDS
    ]
    return words[:4]


_STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "you",
    "your",
    "are",
    "was",
    "were",
    "how",
    "why",
    "what",
    "when",
    "from",
    "about",
    "into",
    "its",
    "just",
    "get",
    "got",
}


def _split_list(value: str) -> list[str]:
    return [piece for piece in re.split(r"[\s,]+", value or "") if piece]


def _unique(values: list[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen

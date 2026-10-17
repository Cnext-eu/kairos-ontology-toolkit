# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Detect and refresh scaffolded ``.github/workflows/*.yml`` files (issue #658).

Workflow files were written once at ``init-hub``/``init-dataplatform`` time and never
touched again, so a real fix landing in a workflow template -- e.g. ``pr-validate.yml``'s
guard against ``local:`` dbt package pins -- could not reach any repo that already
existed. ``update`` reported "all managed files up to date" while silently skipping every
workflow, which is worse than not handling them at all.

Two things rule out the existing managed-file mechanism:

* ``_MANAGED_MARKER_RE`` matches an HTML comment (``<!-- ... -->``), which is not valid
  YAML. Stamping one into a workflow would produce a file GitHub Actions rejects.
* Workflow files legitimately carry real local customization -- environment steps, extra
  credentials, org-specific jobs -- unlike a ``SKILL.md``. Silently overwriting them, or
  failing ``managed-check.yml`` in CI whenever they diverge, would be wrong.

So detection here is *structural* rather than marker- or hash-based. Some workflows are
rendered from a template with ``{PLACEHOLDER}`` substitutions (org, hub repo, release
tag, a whole CI profile block), so their on-disk bytes are repo-specific and no fixed
hash can describe them. :func:`recover_substitutions` inverts the rendering instead: it
answers "is this file an unmodified rendering of this template, and if so with which
values?". That is exactly the question that decides whether refreshing is safe, and it
works identically for templated and non-templated workflows.

Refreshing is opt-in (``update --refresh-workflows``). A plain ``update`` reports drift
and does nothing, because a workflow that no longer matches its template may well be
carrying changes the repo owner made on purpose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: Placeholder syntax used by the scaffold templates (``{ORG}``, ``{DBT_CI_PROFILE_YAML}``).
_PLACEHOLDER = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")

#: Placeholders that also appear in rendered *shell* syntax (``${GITHUB_SHA}``) and are
#: therefore never substituted by the scaffold. Matching them as capture groups would
#: make recovery ambiguous.
_SHELL_ESCAPED = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")

#: A placeholder the scaffold does substitute: ``{NAME}`` not preceded by ``$``. The
#: renderers used to replace every ``{NAME}``, so the deploy workflow's shell variable
#: ``${HUB_REPO}`` became ``$<hub repo>`` and its release lookups pointed at a repository
#: that does not exist (#1114). :func:`classify` still recognises that legacy rendering,
#: as an outdated generation, so a refresh repairs it.
_SUBSTITUTED = re.compile(r"(?<!\$)\{[A-Za-z_][A-Za-z0-9_]*\}")


@dataclass(frozen=True, slots=True)
class WorkflowStatus:
    """One scaffolded workflow's relationship to the template it came from."""

    path: str
    #: "missing" | "current" | "outdated" | "customized"
    state: str
    substitutions: dict[str, str] | None = None

    @property
    def refreshable(self) -> bool:
        """True when rewriting this file cannot destroy local work.

        ``outdated`` means the file is an unmodified rendering of *a* template whose
        content has since changed; ``missing`` means there is nothing to lose.
        """
        return self.state in {"missing", "outdated"}


def _tokens(template: str, *, legacy: bool) -> list[str]:
    """Split *template* into literal text and the placeholders a renderer substitutes.

    *legacy* reproduces the pre-#1114 renderers, which also substituted inside ``${...}``.
    """
    pattern = _PLACEHOLDER if legacy else _SUBSTITUTED
    return [token for token in re.split(f"({pattern.pattern})", template) if token]


def _template_pattern(template: str, *, legacy: bool = False) -> re.Pattern[str]:
    """Build a regex matching any rendering of *template*.

    Each distinct placeholder becomes one capture group; repeat occurrences become
    backreferences, so a rendering where the same placeholder resolved to two different
    values is correctly rejected rather than silently accepted.
    """
    parts: list[str] = []
    seen: dict[str, int] = {}
    index = 0
    substituted = _PLACEHOLDER if legacy else _SUBSTITUTED
    for token in _tokens(template, legacy=legacy):
        if substituted.fullmatch(token):
            name = token[1:-1]
            if name in seen:
                parts.append(f"\\{seen[name]}")
            else:
                index += 1
                seen[name] = index
                parts.append("(.*?)")
            continue
        parts.append(re.escape(token))
    return re.compile("".join(parts) + r"\Z", re.DOTALL)


def _placeholder_names(template: str, *, legacy: bool = False) -> list[str]:
    """Placeholder names in capture-group order, exactly as :func:`_template_pattern`."""
    names: list[str] = []
    substituted = _PLACEHOLDER if legacy else _SUBSTITUTED
    for token in _tokens(template, legacy=legacy):
        if substituted.fullmatch(token):
            name = token[1:-1]
            if name not in names:
                names.append(name)
    return names


def recover_substitutions(
    template: str, actual: str, *, legacy: bool = False
) -> dict[str, str] | None:
    """Return the values *actual* was rendered with, or ``None`` if it was modified.

    ``None`` is the conservative answer: it means the file is not byte-for-byte some
    rendering of *template*, so a refresh would be overwriting something -- possibly a
    stale generation, possibly a deliberate local change. Only the caller's knowledge of
    which templates the toolkit has shipped can tell those apart.
    """
    match = _template_pattern(template, legacy=legacy).match(actual)
    if match is None:
        return None
    recovered = dict(zip(_placeholder_names(template, legacy=legacy), match.groups(), strict=False))
    # A legacy rendering left a name the scaffold never supplied as ``{NAME}``; that is not a
    # value, and carrying it into a refresh would only re-render the placeholder.
    return {name: value for name, value in recovered.items() if value != f"{{{name}}}"}


def render(template: str, substitutions: dict[str, str]) -> str:
    """Render *template*, leaving unknown placeholders and shell ``${...}`` untouched."""

    def replace(match: re.Match[str]) -> str:
        return substitutions.get(match.group()[1:-1], match.group())

    return _SUBSTITUTED.sub(replace, template)


def classify(
    destination: Path,
    current_template: str,
    superseded_templates: tuple[str, ...] = (),
) -> WorkflowStatus:
    """Decide whether *destination* can be safely refreshed from *current_template*.

    A file matching a *superseded* template is an untouched older generation, so
    refreshing it is pure gain. A file matching nothing carries local edits (or a
    generation this toolkit no longer knows) and is only ever reported.
    """
    path = destination.as_posix()
    if not destination.is_file():
        return WorkflowStatus(path, "missing")

    actual = destination.read_text(encoding="utf-8")
    current = recover_substitutions(current_template, actual)
    if current is not None:
        return WorkflowStatus(path, "current", current)

    # The legacy rendering of the current template is outdated, not customized: it is the
    # same file with broken shell variables, and a refresh repairs it (#1114).
    for previous, legacy in (
        (current_template, True),
        *((template, mode) for template in superseded_templates for mode in (False, True)),
    ):
        recovered = recover_substitutions(previous, actual, legacy=legacy)
        if recovered is not None:
            return WorkflowStatus(path, "outdated", recovered)

    return WorkflowStatus(path, "customized")

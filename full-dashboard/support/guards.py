from __future__ import annotations

import json
import re
from dataclasses import dataclass

from support.facts import Facts
from support.models import Evidence, Investigation, Ticket

INJECTION = re.compile(
    r"ignore (?:all |your |the |previous )?(?:instructions|rules)|system\s*prompt|developer\s*message|you are now|act as (?:admin|system)|bypass (?:approval|guardrails)|(?:instructions?|rules?)\s*(?:को|ko)\s*(?:ignore|भूल)|<\|(?:system|im_start)\|>",
    re.I,
)
CRITICAL_SAFETY = re.compile(
    r"\b(?:kill|murder|suicid\w*|self[ -]harm|minor|child|underage|rape|sexual exploitation|death threat)\b|जान से मार|आत्महत्या|नाबालिग",
    re.I,
)
SAFETY = re.compile(
    r"\b(?:harass\w*|abuse|abusive|threat\w*|creep|sexual|stalking)\b|उत्पीड़न|धमकी|गाली", re.I
)
COMPLETED_ACTION = re.compile(
    r"\b(?:we(?:'ve| have)?|your|has been|is now)\b[^.!?\n]{0,50}\b(?:restored|refunded|fixed|banned|deleted|shipped)\b|बहाल कर दिया|रिफंड कर दिया|ban kar diya|restore kar diya",
    re.I,
)
PROMISE = re.compile(
    r"\b(?:will|guarantee[ds]?|definitely|by tomorrow|by next|team is working|team is looking|refund is on|refund has)\b|(?<![\u0900-\u097f])(?:ज़रूर|पक्का)(?![\u0900-\u097f])|ठीक कर देंगे|ho jayega|kar denge",
    re.I,
)

ACKS = {
    "en": "Thanks for reporting this. Your report needs a support review.",
    "hi": "आपकी रिपोर्ट के लिए धन्यवाद। आगे जाँच के लिए इसे सपोर्ट समीक्षा की ज़रूरत है।",
    "hinglish": "Report ke liye shukriya. Isse support review ki zaroorat hai.",
}
FEATURE_ACKS = {
    "en": "Thanks for sharing your suggestion. It is recorded here for product review; there is no release commitment.",
    "hi": "सुझाव साझा करने के लिए धन्यवाद। इसे यहाँ उत्पाद समीक्षा के लिए दर्ज किया गया है; रिलीज़ का कोई वादा नहीं है।",
    "hinglish": "Suggestion share karne ke liye shukriya. Yeh yahan product review ke liye record hua hai; release ka koi commitment nahi hai.",
}


@dataclass
class CheckResult:
    passed: bool
    reasons: list[str]
    claims_found: int
    supported: int


def check_output(
    result: Investigation,
    evidence: list[Evidence],
    facts: Facts,
    ticket_id: str,
    run_id: str,
    ticket: Ticket | None = None,
) -> CheckResult:
    """Fail closed: exact approved wording or independently cited atomic sentences.

    Ticket claims are NEVER proof of an operational fact or proposed action.
    References from another ticket/run cannot support this result.
    Semantic verification of arbitrary paraphrases is a separate, stricter model stage.
    """
    reasons = []
    trusted = {
        e.id: e for e in evidence if e.available and e.ticket_id == ticket_id and e.run_id == run_id
    }
    fact_refs = facts.refs()
    refs = set(trusted) | set(fact_refs)
    if not result.user_reply_draft.strip():
        reasons.append("Missing user-facing draft")
    for pattern, reason in (
        (COMPLETED_ACTION, "Claims an action already happened"),
        (PROMISE, "Contains a promise or unconfirmed team activity"),
    ):
        if pattern.search(result.user_reply_draft):
            reasons.append(reason)
    if set(result.evidence_refs) - refs:
        reasons.append("Unknown, unavailable, or stale evidence reference")
    canonical = set(ACKS.values()) | set(FEATURE_ACKS.values())
    approved_facts = facts.verified(ticket.category.value if ticket else None)
    approved = {
        a
        for f in approved_facts
        for language, a in f.get("answers", {}).items()
        if ticket is None or language == ticket.language
    }
    supported = 0
    generated_supported = False
    if ticket is not None and ticket.id == ticket_id and ticket.active_run == run_id:
        from support.branches import independently_supported

        generated_supported = independently_supported(result, ticket, evidence, facts)
    if result.user_reply_draft not in canonical | approved and not generated_supported:
        # No model-authored factual sentence bypasses review by omitting claims.
        reasons.append("Draft requires independent semantic fact verification")
    if result.user_reply_draft in approved and result.user_reply_draft not in canonical:
        matching = {
            f"fact:{f['id']}"
            for f in approved_facts
            if result.user_reply_draft in f.get("answers", {}).values()
        }
        if not matching.intersection(result.evidence_refs):
            reasons.append("Approved wording requires its matching policy reference")
    if result.proposed_actions and not generated_supported:
        reasons.append("Internal actions require an independently computed branch proposal")
    for claim in result.claims:
        if (
            generated_supported
            and claim.text == result.user_reply_draft
            and claim.evidence_refs == result.evidence_refs
        ):
            supported += 1
            continue
        matching_facts = [fact_refs[r] for r in claim.evidence_refs if r in fact_refs]
        if (
            claim.evidence_refs
            and not (set(claim.evidence_refs) - refs)
            and any(claim.text in f.get("answers", {}).values() for f in matching_facts)
        ):
            supported += 1
        else:
            reasons.append("Atomic claim lacks exact verified policy support")
    for action in result.proposed_actions:
        try:
            payload = json.loads(action.payload)
            if not isinstance(payload, dict):
                raise ValueError
        except (ValueError, TypeError):
            reasons.append("Action payload must be a JSON object")
            continue
        if action.type != "send_reply" and (
            not action.evidence_refs or set(action.evidence_refs) - refs
        ):
            reasons.append("Action lacks current, available evidence")
        if action.type == "send_reply" and payload.get("text") != result.user_reply_draft:
            reasons.append("Reply action differs from checked draft")
        if action.type == "temp_ban_messaging" and not generated_supported:
            reasons.append("Ban proposal requires a verified severity policy and human review")
        # A proposal reason/payload is also user-editable model output.
        if COMPLETED_ACTION.search(action.reason) or PROMISE.search(action.reason):
            reasons.append("Action reason contains an unsupported outcome or promise")
    return CheckResult(not reasons, list(dict.fromkeys(reasons)), len(result.claims), supported)

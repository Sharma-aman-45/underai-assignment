"""Deterministic triage that applies policy.md precedence.
 
Pipeline:
  1. Normalise and split the ticket into sentences.
  2. Drop sentences that look like embedded instructions (prompt injection).
  3. For incident detection only, also remove quoted spans and
     hypothetical / negated sentences, so examples are not treated as incidents.
  4. Apply policy rules 1-6 in order; the first match wins.
 
No case IDs or baseline decisions are used here.
"""
 
import re
 
# --- Prompt-injection markers (sentence is dropped entirely) -----------------
INJECTION = re.compile(
    r"\bsystem\s*:|\bignore (all |any |your |the |previous |prior )*(rules|instructions|policy)"
    r"|\boverride\b.*\b(policy|rules)\b|\byou are now\b|\bclassify (this|it) as\b"
    r"|\b(route|action|priority|escalate)\s*[=:]\s*\w+"
    r"|\b(note|message|instructions?) (to|for) (the )?(ai|assistant|bot|model|classifier|triage)\b"
    r"|\bassistant instructions?\b"
)
 
# --- Quotes, hypotheticals, negated incidents (ignored for rule 1) -----------
QUOTED = re.compile(r"\"[^\"]*\"|\u201c[^\u201d]*\u201d|(?<![a-z])'[^']*'(?![a-z])")
HYPOTHETICAL = re.compile(
    r"\b(for example|an example|example of|hypothetical(ly)?|what if|imagine|pretend"
    r"|sample ticket|test ticket|training (deck|material|example)|for a demo|mock"
    r"|what (would|should) (happen|i do)|in case"
    r"|if (my|an|a|the|our) \w+( \w+)? (were|was|is|gets|got|ever))\b"
)
NEGATED_INCIDENT = re.compile(
    r"\b(no|not|never|nothing|didn't|did not|wasn't|was not|hasn't|has not|isn't)\b"
    r"(\s+\w+){0,3}\s+(leak|leaked|compromised|hacked|breached|exposed|stolen)\b"
)
 
# --- Rule 1: safety / security incident -------------------------------------
SECRET = r"(api )?(token|key|password|credential|credentials|secret)s?"
INCIDENT = re.compile(
    rf"\b{SECRET}\b.*\b(leak|leaked|exposed|public|pasted|posted|committed|stolen)\b"
    rf"|\b(leak|leaked|exposed|pasted|posted|committed|stolen)\b.*\b{SECRET}\b"
    r"|\b(hacked|compromised|taken over|breach|breached|unauthori[sz]ed)\b"
    r"|\b(was not me|wasn't me|not me)\b"
    r"|\bdid(n't| not) (do|make|authori[sz]e|request|change) (this|that|it)\b"
    r"|\bsomeone (else )?(is |may be |might be |has been )?(using|logged|logging|accessing|accessed)\b"
    r"|\bcustomer data\b.*\b(exposed|leaked|public)\b"
    r"|\b(active abuse|being abused|fraudulent (use|activity))\b"
)
 
# --- Rule 2: someone else's private data ------------------------------------
OTHER_PERSON = (
    r"(co-?worker|colleague|boss|manager|employee|teammate|friend|partner|wife|husband"
    r"|another user|other user|someone else|another customer|another person)"
)
PRIVATE_THING = (
    r"(data|logs|email|e-mail|address|password|credentials|records|account|phone"
    r"|details|history|messages|files|information)"
)
THIRD_PARTY = re.compile(
    rf"\b{OTHER_PERSON}('s|s')?(\s+\w+){{0,3}}\s+{PRIVATE_THING}\b"
    rf"|\b(which|what)\b[^.?!]*\b{PRIVATE_THING}\b[^.?!]*\b{OTHER_PERSON}\b"
    rf"|\b{PRIVATE_THING} (of|for|belonging to) (my |our |a |the )?{OTHER_PERSON}\b"
)
 
# --- Rule 3: privacy rights / privacy questions ------------------------------
RIGHTS_VERB = r"(delet|eras|remov|wipe|export|download|copy|correct|rectif|updat)"
PERSONAL_DATA = (
    r"(personal (data|information|info)|my (account |user |customer )?data|all (of )?my data|my information"
    r"|data you (hold|have|store|keep)|information you (hold|have|store|keep))"
)
PRIVACY_RIGHTS = re.compile(
    rf"\b{RIGHTS_VERB}\w*\b.*\b{PERSONAL_DATA}|\b{PERSONAL_DATA}\b.*\b{RIGHTS_VERB}\w*"
    r"|\b(delete|erase|close) my account\b|\bright to be forgotten\b|\b(dsar|data subject access|gdpr request)\b"
)
PRIVACY_QUESTION = re.compile(
    r"\b(privacy policy|privacy terms|privacy practices|retention|gdpr|data processing"
    r"|cookie policy|dpa)\b"
)
 
# --- Rule 4: account access ---------------------------------------------------
ACCESS_CHANGE = re.compile(
    r"\b(reset|change|recover|forgot|forgotten)\b.*\bpassword\b|\bpassword reset\b"
    r"|\b(change|update|switch)\b.*\b(email|e-mail)\b"
    r"|\b(disable|turn off|remove|reset|bypass|deactivate|switch off)\b.*\b(mfa|2fa|two-factor|authenticator)\b"
    r"|\b(mfa|2fa|two-factor)\b.*\b(disable|turn off|remove|off)\b"
    r"|\bunlock\b|\blocked out\b"
)
ACCESS_GENERAL = re.compile(
    r"\b(sign-?in|sign in|log ?in|login|logging in|sso|password|mfa|2fa|can't access|cannot access)\b"
)
 
# --- Rule 5: billing ------------------------------------------------------------
BILLING = re.compile(
    r"\b(charg\w*|refund\w*|invoice\w*|billing|bill|price|pricing|cost\w*|plan|subscription"
    r"|chargeback|receipt|payment|paid|overcharg\w*)\b"
)
 
 
def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]
 
 
def clean(ticket):
    """Return (text, incident_text).
 
    text          -> injection sentences removed; used for rules 2-6
    incident_text -> additionally strips quotes, hypotheticals and negated
                     incidents; used for rule 1 only
    """
    raw = f"{ticket.get('subject', '')}. {ticket.get('body', '')}".lower()
    kept = [s for s in _sentences(raw) if not INJECTION.search(s)]
 
    incident_parts = []
    for sentence in kept:
        sentence = QUOTED.sub(" ", sentence)
        if HYPOTHETICAL.search(sentence) or NEGATED_INCIDENT.search(sentence):
            continue
        incident_parts.append(sentence)
    return " ".join(kept), " ".join(incident_parts)
 
 
def classify(ticket):
    """Return (route, action, priority, reason) following policy.md order."""
    text, incident_text = clean(ticket)
 
    if INCIDENT.search(incident_text):
        return "safety", "escalate", "urgent", "rule1_incident"
    if THIRD_PARTY.search(text):
        return "privacy", "refuse", "normal", "rule2_third_party"
    if PRIVACY_RIGHTS.search(text):
        return "privacy", "verify_identity", "normal", "rule3_privacy_rights"
    if PRIVACY_QUESTION.search(text):
        return "privacy", "reply", "normal", "rule3_privacy_question"
    if ACCESS_CHANGE.search(text):
        return "access", "verify_identity", "normal", "rule4_access_change"
    if ACCESS_GENERAL.search(text):
        return "access", "reply", "normal", "rule4_access_troubleshooting"
    if BILLING.search(text):
        return "billing", "reply", "normal", "rule5_billing"
    return "general", "reply", "normal", "rule6_general"
 
 
def decide(ticket):
    route, action, priority, _ = classify(ticket)
    return {
        "id": ticket["id"],
        "route": route,
        "action": action,
        "priority": priority,
        "escalate": action == "escalate",
    }
 
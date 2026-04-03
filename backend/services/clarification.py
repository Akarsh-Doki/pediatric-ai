import re
import logging

logger = logging.getLogger("pediatricai")

# Medical specificity indicators — if present, the query is specific enough
SPECIFIC_INDICATORS = [
    # Temperature numbers
    r"\d{2,3}(\.\d+)?\s*(degree|f|°|fever)",
    r"(fever|temp)\s*(of\s*)?\d{2,3}",
    # Named conditions
    r"(rash|cough|vomit|diarrhea|earache|ear\s*infection|sore\s*throat|congestion|"
    r"croup|bronchiol|asthma|eczema|hives|burn|choking|seizure|concussion|"
    r"pink\s*eye|conjunctiv|strep|flu|cold|uti|constipat|teething|lice|ringworm|"
    r"nosebleed|splinter|sunburn|sprain|fracture|allergic|anaphyla|poison|"
    r"chickenpox|measles|mumps|whooping|rsv|hand\s*foot|diaper\s*rash|cradle\s*cap)",
    # Specific symptoms
    r"(barking|won't eat|not eating|throwing up|can't breathe|wheezing|"
    r"blood in|swollen|stiff neck|blue lips|limp|unresponsive|"
    r"pulling\s*(at\s*)?ear|red\s*(nose|eye|skin|cheek)|"
    r"runny\s*nose|stuffy|difficulty\s*(breathing|swallowing)|"
    r"spots|bumps|blisters|swelling|itching|scratching)",
    # Medication questions
    r"(tylenol|motrin|advil|ibuprofen|acetaminophen|benadryl|zyrtec|antibiotic|"
    r"amoxicillin|medication|medicine|dosage|dose)",
    # Body parts with issues
    r"(head|stomach|throat|chest|arm|leg|hand|foot|finger|toe|eye|ear|nose|mouth|knee|ankle)\s+"
    r"(hurts|pain|sore|swollen|red|bleeding|broken|bump)",
    # Action questions
    r"(when\s*should\s*i|should\s*i\s*take|is\s*it\s*(safe|ok|normal)|how\s*(much|long|often))",
    # Vaccine/schedule questions
    r"(vaccine|immuniz|shot|booster|schedule|milestone|development)",
    # ER/emergency questions
    r"(er|emergency|urgent\s*care|hospital|911|poison\s*control)",
]

# Vague patterns that signal ambiguity
VAGUE_PATTERNS = [
    r"^(my\s*(child|kid|baby|son|daughter|toddler|infant)\s*is\s*sick)\.?$",
    r"^(not\s*feeling\s*well|feeling\s*(bad|sick|unwell|off))\.?$",
    r"^(something\s*is\s*wrong|something\s*seems\s*(wrong|off))\.?$",
    r"^(i'?m\s*worried|i'?m\s*concerned|should\s*i\s*be\s*worried)\.?$",
    r"^(help|help\s*me|i\s*need\s*help)\.?$",
    r"^(what\s*do\s*i\s*do|what\s*should\s*i\s*do)\.?$",
    r"^(is\s*this\s*(normal|ok|bad|serious))\.?$",
]

# Context-aware follow-up questions based on partial clues
CONTEXTUAL_FOLLOWUPS = {
    "fever": "How high is the temperature, and how old is your child? Has the fever lasted more than 24 hours?",
    "rash": "Where on the body is the rash? Is it raised, flat, or blistered? Is it itchy?",
    "cough": "What does the cough sound like — dry, wet, or barking? Is it worse at night? Any difficulty breathing?",
    "pain": "Where exactly is the pain? How long has it been going on? Did anything specific cause it?",
    "vomit": "How many times has your child vomited? Is there any blood in it? Can they keep down liquids?",
    "breathing": "Is your child having trouble breathing right now? Do you hear wheezing or a whistling sound?",
    "fall": "How far did they fall and what did they land on? Are they alert and acting normally? Any visible swelling or bruising?",
    "swallow": "Did your child swallow something? Do you know what it was and how much?",
    "eye": "Is the eye red, swollen, or producing discharge? Is it in one eye or both?",
    "ear": "Is your child pulling at their ear? Do they have a fever along with it? Any fluid draining from the ear?",
    "bite": "What bit your child — an insect, animal, or another child? Is there swelling or redness spreading from the bite?",
    "head": "Did your child hit their head? Are they alert, vomiting, or acting confused?",
}

# Generic follow-up for completely vague queries
GENERIC_FOLLOWUP = (
    "I want to help! Can you tell me a bit more about what's going on? "
    "For example:\n"
    "- What symptoms are you seeing? (fever, cough, rash, pain, etc.)\n"
    "- When did it start?\n"
    "- How old is your child?"
)


def detect_ambiguity(message: str) -> dict:
    """
    Analyze a user message for ambiguity.
    
    Returns:
        {
            "is_ambiguous": bool,
            "followup_question": str or None,
            "reason": str  -- why it was flagged (for logging)
        }
    """
    text = message.strip()
    text_lower = text.lower()

    # Skip ambiguity check for greetings and very short casual messages
    greetings = ["hi", "hello", "hey", "thanks", "thank you", "ok", "okay", "bye", "goodbye"]
    if text_lower.rstrip("!. ") in greetings:
        return {"is_ambiguous": False, "followup_question": None, "reason": "greeting"}

    # Check if the query has specific medical indicators
    for pattern in SPECIFIC_INDICATORS:
        if re.search(pattern, text_lower):
            return {"is_ambiguous": False, "followup_question": None, "reason": "specific_query"}

    # Check for explicitly vague patterns
    for pattern in VAGUE_PATTERNS:
        if re.search(pattern, text_lower):
            # Try to find a contextual clue for a targeted follow-up
            followup = _find_contextual_followup(text_lower)
            return {
                "is_ambiguous": True,
                "followup_question": followup,
                "reason": "vague_pattern",
            }

    # Check if the query is too short to retrieve meaningfully (under 4 real words)
    words = [w for w in text_lower.split() if len(w) > 2]  # skip "my", "is", "a", etc.
    if len(words) < 3:
        followup = _find_contextual_followup(text_lower)
        return {
            "is_ambiguous": True,
            "followup_question": followup,
            "reason": "too_short",
        }

    # Not ambiguous — proceed with retrieval
    return {"is_ambiguous": False, "followup_question": None, "reason": "sufficient_detail"}


def _find_contextual_followup(text_lower: str) -> str:
    """Find the best follow-up question based on any partial clues in the message."""
    for clue, followup in CONTEXTUAL_FOLLOWUPS.items():
        if clue in text_lower:
            return followup
    return GENERIC_FOLLOWUP
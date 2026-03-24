"""Extract symptoms from user messages for the symptom_extractions table."""
import re

# Common symptom keywords grouped by severity signal
SYMPTOM_KEYWORDS = {
    "fever": ["fever", "temperature", "hot", "burning up"],
    "rash": ["rash", "spots", "bumps", "hives", "red skin", "blotchy"],
    "cough": ["cough", "coughing", "barking cough", "wheezing"],
    "vomiting": ["vomit", "throwing up", "puking", "sick to stomach"],
    "diarrhea": ["diarrhea", "loose stool", "watery stool", "runs"],
    "pain": ["pain", "hurts", "ache", "sore", "tender", "cramping"],
    "breathing_difficulty": ["breathing", "can't breathe", "wheezing", "gasping", "short of breath"],
    "congestion": ["congestion", "stuffy nose", "runny nose", "blocked nose"],
    "earache": ["ear pain", "ear ache", "pulling ear", "ear hurts"],
    "headache": ["headache", "head hurts", "head pain"],
    "swelling": ["swelling", "swollen", "puffy", "inflamed"],
    "bleeding": ["bleeding", "blood", "cut", "wound"],
    "fatigue": ["tired", "fatigue", "lethargic", "no energy", "sleepy", "drowsy"],
    "seizure": ["seizure", "convulsion", "shaking", "fitting"],
    "choking": ["choking", "can't swallow", "gagging", "blue lips"],
    "loss_of_appetite": ["won't eat", "not eating", "no appetite", "refusing food"],
    "eye_issue": ["eye", "red eye", "pink eye", "watery eyes", "discharge"],
    "throat": ["sore throat", "throat hurts", "difficulty swallowing"],
}

SEVERE_KEYWORDS = ["unconscious", "not breathing", "blue", "seizure", "choking",
                    "unresponsive", "limp", "poison", "ingested", "severe bleeding",
                    "anaphylaxis", "swelling throat"]

MODERATE_KEYWORDS = ["high fever", "103", "104", "105", "won't stop vomiting",
                     "dehydrated", "blood in stool", "difficulty breathing",
                     "stiff neck", "can't walk"]

def extract_symptoms(text: str) -> dict:
    """Extract symptoms and estimate severity from user message text."""
    text_lower = text.lower()
    found_symptoms = []

    for symptom, keywords in SYMPTOM_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                found_symptoms.append(symptom)
                break

    # Estimate severity
    severity = "unknown"
    if any(kw in text_lower for kw in SEVERE_KEYWORDS):
        severity = "severe"
    elif any(kw in text_lower for kw in MODERATE_KEYWORDS):
        severity = "moderate"
    elif found_symptoms:
        severity = "mild"

    return {
        "symptoms": list(set(found_symptoms)),
        "severity_estimate": severity,
    }
"""Runtime language policy; never rewrites the clinic's saved prompt or greeting."""

SUPPORTED_LANGUAGES = {"en-US": "English", "hi-IN": "Hindi", "es-US": "Spanish"}

# Retain names for legacy saved agents; new editor choices come from the supported set.
LANGUAGES = {
    "en-US": "English (US)",
    "en-GB": "English (UK)",
    "es-US": "Spanish (US)",
    "fr-FR": "French",
    "de-DE": "German",
    "hi-IN": "Hindi",
}


def conversation_language(agent: dict) -> str:
    return LANGUAGES.get(agent.get("language", "en-US"), agent.get("language", "en-US"))


def language_instruction(agent: dict) -> str:
    return (
        f"Conversation language: {conversation_language(agent)}. "
        "Speak in this selected language, including the opening "
        "greeting, even when the configured prompt or greeting is written in another language. "
        "Understand callers speaking this language. Follow an explicit caller request to switch languages; "
        "natural code-switching between the selected language and English is allowed. "
        "These language and storage rules apply independently of the clinic's configured prompt. "
        "Transcripts must preserve the actual spoken language; do not translate the conversation for transcription. "
        "When calling save_caller_details or other tools, translate descriptive text values into English. "
        "Transliterate personal and place names into Latin letters without translating their meaning. "
        "Keep schema keys and exact enum options unchanged. Use ASCII digits, E.164 phone numbers, ISO dates, "
        "numbers and booleans in their required formats. Preserve email addresses, URLs, IDs and other exact "
        "identifiers; never invent missing information. Tool search queries may retain the caller's language "
        "when needed to find relevant knowledge. Confirm important details aloud in the conversation language."
    )

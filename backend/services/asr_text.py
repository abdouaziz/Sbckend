"""Post-processing of transcriptions, kept free of heavy imports so it can be tested alone."""
import re

# Language tags added to the tokenizer by the fine-tuning (<|wo|>, <|pu|>, <|se|>) are not
# registered as special tokens, so skip_special_tokens keeps them: remove them like
# Whisper removes its own language tokens.
_LANGUAGE_TAG = re.compile(r"<\|[a-z]{2,3}\|>")


def clean_transcription(text: str) -> str:
    return " ".join(_LANGUAGE_TAG.sub(" ", text).split())

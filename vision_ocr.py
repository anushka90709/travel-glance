"""OCR fallback for PDFs with no embedded text layer, via an OpenAI vision model.

Used only when extract_pdf_text() comes back empty - renders the PDF's pages
as images and asks a vision-capable model to transcribe what's on them. The
recovered text is then handed to the existing text-based extract_with_llm()
pipeline, not parsed here - this module's only job is "picture -> text."

Same defensive contract as llm_extractor.py: checks OPENAI_API_KEY itself,
never raises, returns None on any failure so the caller can fall back to the
generic parser exactly as it did before this existed.
"""
import base64
import os

import truststore
truststore.inject_into_ssl()  # trust the Windows cert store (corporate proxy TLS)

import pymupdf
from openai import OpenAI

VISION_MODEL = "gpt-5-mini"
REQUEST_TIMEOUT_SECONDS = 30
# Only ever send two requests per PDF: a full transcription of page 1 (the
# itinerary), and a short, *targeted* fare question on page 2, where
# fare/payment summaries live on multi-page e-tickets (confirmed against a
# real IndiGo ticket: page 1 = itinerary, page 2 = fare summary + baggage
# info, pages 3+ = boilerplate terms, last page often near-blank - "page 2"
# is the reliable target, not "last page"). A narrow targeted question is
# both cheaper and more reliable than transcribing every page just to keep
# one number.
RENDER_ZOOM = 2.0

TRANSCRIBE_PROMPT = (
    "This is a page from a flight ticket or travel itinerary. Transcribe every "
    "piece of text visible in the image exactly as it appears - passenger name, "
    "dates, times, cities, airline, flight number, PNR/booking reference, fare "
    "or price or total amount, everything. Preserve line breaks and layout "
    "where you can. Output only the transcribed text, no commentary."
)

PRICE_PROMPT = (
    "Look at this ticket/itinerary page for a total fare, total price, grand "
    "total, or total amount paid. Reply with just that single line, e.g. "
    "'Total fare: INR 28,622' - include the currency. If no such amount is "
    "visible anywhere on this page, reply with exactly: NONE"
)


def extract_text_via_vision(path_or_stream):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        if hasattr(path_or_stream, "read"):
            path_or_stream.seek(0)
            pdf_bytes = path_or_stream.read()
        else:
            with open(path_or_stream, "rb") as f:
                pdf_bytes = f.read()
        page_images = _render_key_pages_to_base64(pdf_bytes)
    except Exception:
        return None

    if not page_images:
        return None

    client = OpenAI(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS)
    texts = []

    first_page_text = _call_vision(client, page_images[0], TRANSCRIBE_PROMPT, max_completion_tokens=2048)
    if first_page_text:
        texts.append(first_page_text)

    if len(page_images) > 1:
        price_answer = _call_vision(client, page_images[1], PRICE_PROMPT, max_completion_tokens=1500)
        if price_answer and "NONE" not in price_answer.upper():
            texts.append(price_answer)

    combined = "\n\n".join(texts)
    return combined if combined.strip() else None


def _call_vision(client, image_b64, prompt, max_completion_tokens):
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
    ]
    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=VISION_MODEL,
                messages=[{"role": "user", "content": content}],
                reasoning_effort="low",  # a transcription/lookup task doesn't need deep reasoning
                max_completion_tokens=max_completion_tokens,
            )
            return response.choices[0].message.content or ""
        except Exception:
            if attempt == 0:
                continue
            return None
    return None


def _render_key_pages_to_base64(pdf_bytes):
    """Page 1, plus page 2 too (if there is one) - see comment above."""
    images = []
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        if len(doc) == 0:
            return images
        page_indices = [0] if len(doc) == 1 else [0, 1]
        for i in page_indices:
            pix = doc[i].get_pixmap(matrix=pymupdf.Matrix(RENDER_ZOOM, RENDER_ZOOM))
            images.append(base64.b64encode(pix.tobytes("png")).decode("ascii"))
    return images

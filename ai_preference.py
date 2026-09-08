import json
import os
import requests
from dotenv import load_dotenv

load_dotenv()

URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM = """
You are SwapCycle's bounded preference-normalization component.

Your ONLY job is to convert a user's natural-language item trading
preference into structured JSON.

IMPORTANT RULES:
- Do NOT choose a trading partner.
- Do NOT create exchange cycles.
- Do NOT perform matching.
- Do NOT make the final matching decision.
- Do NOT rank users.
- Do NOT invent information that the user did not provide.
- Do NOT add brands unless the user mentioned them or explicitly allowed
  similar alternatives.
- Use numeric values between 0.0 and 1.0 for budget_or_value_signal
  and flexibility.
- Do NOT invent information that the user did not provide.
- Do NOT infer a specific item type, material, model, or feature unless it is
  explicitly stated or strongly implied by the user's wording.
- Return JSON only.
- Do not include explanations outside the JSON.

Return exactly this structure:

{
  "item_category": "string",
  "desired_item": "string",
  "acceptable_brands": ["string"],
  "minimum_condition": "new|like_new|good|fair|any",
  "budget_or_value_signal": 0.0,
  "flexibility": 0.0,
  "keywords": ["string"],
  "notes": "string"
}

Interpretation guidelines:

item_category:
- General category of the item the user wants.
- Example: "guitar", "camera", "bicycle".

desired_item:
- The specific item requested.
- Example: "beginner-friendly acoustic guitar".

acceptable_brands:
- Brands explicitly mentioned by the user.
- If the user says "Yamaha or similar", include "Yamaha".

minimum_condition:
- Use the strongest minimum condition explicitly stated.
- Allowed values: new, like_new, good, fair, any.
- If no condition is specified, use "any".

budget_or_value_signal:
- 0.0 means no budget/value preference was expressed.
- 1.0 means a very strong budget/value requirement was expressed.
- Estimate conservatively from the user's wording.

flexibility:
- 0.0 means very strict requirements.
- 1.0 means highly flexible requirements.
- Estimate from wording such as "must", "preferably", "or similar",
  "anything is fine", etc.

keywords:
- Important search terms extracted from the preference.
- Keep them concise.

notes:
- Briefly preserve useful preference details that do not fit elsewhere.
"""


EXPECTED_FIELDS = {
    "item_category",
    "desired_item",
    "acceptable_brands",
    "minimum_condition",
    "budget_or_value_signal",
    "flexibility",
    "keywords",
    "notes"
}


def normalize_preference(text):
    """
    Convert natural-language trading preferences into structured JSON.

    The AI only interprets the preference.
    BGCC remains responsible for the actual matching decision.
    """

    if not text or not text.strip():
        raise ValueError("Preference text cannot be empty.")

    key = os.getenv("OPENROUTER_API_KEY")

    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY was not found.\n"
            "Put your rotated OpenRouter API key in the .env file."
        )

    model = os.getenv(
        "OPENROUTER_MODEL",
        "google/gemini-2.5-flash-lite"
    )

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "SwapCycle AI Preference Normalizer"
    }

    payload = {
        "model": model,
        "temperature": 0.1,
        "max_tokens": 400,
        "messages": [
            {
                "role": "system",
                "content": SYSTEM
            },
            {
                "role": "user",
                "content": text.strip()
            }
        ],
        "response_format": {
            "type": "json_object"
        }
    }

    print("Connecting to OpenRouter...")
    print(f"Model: {model}")

    # ---------------------------------------------------------
    # Send request
    # ---------------------------------------------------------

    try:
        response = requests.post(
            URL,
            headers=headers,
            json=payload,
            timeout=60
        )

    except requests.RequestException as e:
        raise RuntimeError(
            f"Could not connect to OpenRouter:\n{e}"
        )

    # ---------------------------------------------------------
    # Handle HTTP errors
    # ---------------------------------------------------------

    if not response.ok:

        try:
            error_data = response.json()

            print("\nOpenRouter error response:")
            print(json.dumps(error_data, indent=2))

        except ValueError:

            print("\nOpenRouter raw response:")
            print(response.text)

        raise RuntimeError(
            f"OpenRouter returned HTTP {response.status_code}."
        )

    # ---------------------------------------------------------
    # Parse OpenRouter response
    # ---------------------------------------------------------

    try:
        data = response.json()

    except ValueError:
        raise RuntimeError(
            "OpenRouter returned a response that was not valid JSON."
        )

    # ---------------------------------------------------------
    # Show actual model used
    # ---------------------------------------------------------

    actual_model = data.get("model")

    if actual_model:
        print(f"Actual model used: {actual_model}")

    # ---------------------------------------------------------
    # Check choices
    # ---------------------------------------------------------

    choices = data.get("choices")

    if not choices:
        raise RuntimeError(
            "OpenRouter returned no choices.\n\n"
            "Full response:\n"
            + json.dumps(data, indent=2)
        )

    # ---------------------------------------------------------
    # Extract message content
    # ---------------------------------------------------------

    message = choices[0].get("message", {})
    content = message.get("content")

    if not content:

        raise RuntimeError(
            "The selected model returned no text content.\n\n"
            "Full response:\n"
            + json.dumps(data, indent=2)
        )

    content = content.strip()

    # ---------------------------------------------------------
    # Remove Markdown code fences
    # ---------------------------------------------------------

    if content.startswith("```"):

        if content.startswith("```json"):
            content = content[len("```json"):]

        elif content.startswith("```"):
            content = content[len("```"):]

        if content.endswith("```"):
            content = content[:-3]

        content = content.strip()

    # ---------------------------------------------------------
    # Convert AI output to Python dictionary
    # ---------------------------------------------------------

    try:
        result = json.loads(content)

    except json.JSONDecodeError:

        raise RuntimeError(
            "The AI returned text, but it was not valid JSON.\n\n"
            "AI output:\n"
            + content
        )

    # ---------------------------------------------------------
    # Validate returned structure
    # ---------------------------------------------------------

    if not isinstance(result, dict):

        raise RuntimeError(
            "The AI returned valid JSON, but the result was not a JSON object.\n\n"
            "AI output:\n"
            + json.dumps(result, indent=2)
        )

    missing_fields = EXPECTED_FIELDS - set(result.keys())

    if missing_fields:

        raise RuntimeError(
            "The AI returned JSON, but some required fields are missing.\n\n"
            f"Missing fields: {sorted(missing_fields)}\n\n"
            "AI output:\n"
            + json.dumps(result, indent=2)
        )

    # ---------------------------------------------------------
    # Validate condition
    # ---------------------------------------------------------

    allowed_conditions = {
        "new",
        "like_new",
        "good",
        "fair",
        "any"
    }

    condition = result.get("minimum_condition")

    if condition not in allowed_conditions:

        result["minimum_condition"] = "any"

    # ---------------------------------------------------------
    # Validate numeric scores
    # ---------------------------------------------------------

    for field in [
        "budget_or_value_signal",
        "flexibility"
    ]:

        try:
            value = float(result[field])

        except (TypeError, ValueError):

            value = 0.0

        # Keep value between 0.0 and 1.0
        value = max(0.0, min(1.0, value))

        result[field] = value

    # ---------------------------------------------------------
    # Validate list fields
    # ---------------------------------------------------------

    if not isinstance(result["acceptable_brands"], list):
        result["acceptable_brands"] = []

    if not isinstance(result["keywords"], list):
        result["keywords"] = []

    # ---------------------------------------------------------
    # Return clean result
    # ---------------------------------------------------------

    return result


# =============================================================
# Test the AI component directly
# =============================================================

if __name__ == "__main__":

    test_text = (
        "I want a beginner-friendly guitar, preferably Yamaha or similar. "
        "A good-condition used one is fine."
    )

    print(
        "\n=== SwapCycle AI Preference Normalization ===\n"
    )

    try:

        result = normalize_preference(test_text)

        print("\nNormalized preference:")
        print(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False
            )
        )

        print("\nAI role:")
        print("Preference interpretation ONLY")

        print("\nMatching role:")
        print("BGCC algorithm")

        print("\nStatus:")
        print("SUCCESS")

    except Exception as e:

        print("\nERROR:")
        print(e)
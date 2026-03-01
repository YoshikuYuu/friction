from dotenv import load_dotenv
import json
from google import genai
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from category import CategoryConfig

# The client gets the API key from the environment variable `GEMINI_API_KEY`.

class ExampleGenerator:
    def __init__(self):
        load_dotenv()
        try:
            self.client = genai.Client()
        except Exception as e:
            print("Error initializing Gemini client:", e)
            raise
    
    def generate_examples(self, category_description: str) -> List[str]:
        """
        Generates examples based on the given prompt using Gemini.
        """
        if not category_description.strip():
            raise ValueError("Topic must be a non-empty string.")

        min_cases, max_cases = 3, 6
        prompt = (
            "You are helping define the boundary of a semantic category that will be used to describe websites that the user wants to block.\n"
            "User-provided category description:\n"
            f"\"\"\"{category_description.strip()}\"\"\"\n"
            f"Task: Generate {min_cases} to {max_cases} DISTINCT semantically related categories. These categories should:\n"
            "- Cover related categories that overlap semantically (including subset/superset relationships) with the user's category"
            "- Cover categories that possibly fall under the user provided category, but not clearly. Avoid synonyms!\n"
            "- Be realistic and appropriate in scope (i.e. if the user's category is very broad, your suggestions should be roughly similar in breadth)\n"
            "Return ONLY a JSON array of short strings describing your suggested categories. Each string should be no longer than 10 words. No explanation."
        )

        response = self.client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_json_schema": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": min_cases,
                    "maxItems": max_cases,
                },
            },
        )

        try:
            data = json.loads(response.text or "[]")
        except json.JSONDecodeError as e:
            raise ValueError("Gemini returned non-JSON output.") from e

        if not isinstance(data, list):
            raise ValueError("Gemini returned JSON that is not a list.")

        normalized = [item.strip() for item in data if isinstance(item, str) and item.strip()]
        return normalized

    def generate_probe_dataset(self, cfg: "CategoryConfig", n: int = 200) -> dict[str, List[str]]:
        if n < 2 or n % 2 != 0:
            raise ValueError("n must be an even integer >= 2.")

        half = n // 2
        prompt = (
            "You are generating synthetic supervised fine-tuning data for a linear probe classifier over text embeddings.\n"
            "The classifier should detect whether web queries/page titles belong to a target category.\n"
            "Generate highly varied, diverse, realistic, and boundary-aware examples.\n"
            "Include people, products, search queries, slang, short phrases, entities, and web page title-like strings.\n"
            "Avoid duplicates and avoid near-duplicates.\n"
            "Category name:\n"
            f"\"\"{cfg.name.strip()}\"\"\"\n"
            "Category definition:\n"
            f"\"\"{cfg.initial_definition.strip()}\"\"\"\n"
            "Positive anchor tags:\n"
            f"\"\"{json.dumps(cfg.positive_definitions, ensure_ascii=False)}\"\"\"\n"
            "Negative anchor tags:\n"
            f"\"\"{json.dumps(cfg.negative_definitions, ensure_ascii=False)}\"\"\"\n"
            f"Return EXACTLY a JSON object with two fields: 'positive' and 'negative'.\n"
            f"'positive' must be a JSON array of exactly {half} strings that belong in the category.\n"
            f"'negative' must be a JSON array of exactly {half} strings that do not belong in the category.\n"
            "Output ONLY valid JSON. No prose."
        )

        response = self.client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_json_schema": {
                    "type": "object",
                    "properties": {
                        "positive": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": half,
                            "maxItems": half,
                        },
                        "negative": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": half,
                            "maxItems": half,
                        },
                    },
                    "required": ["positive", "negative"],
                    "additionalProperties": False,
                },
            },
        )

        try:
            payload = json.loads(response.text or "{}")
        except json.JSONDecodeError as e:
            raise ValueError("Gemini returned non-JSON output for probe dataset.") from e

        if not isinstance(payload, dict):
            raise ValueError("Gemini returned JSON that is not an object.")

        positives = payload.get("positive", [])
        negatives = payload.get("negative", [])
        if not isinstance(positives, list) or not isinstance(negatives, list):
            raise ValueError("Gemini output must contain list fields 'positive' and 'negative'.")

        normalized_pos = [item.strip() for item in positives if isinstance(item, str) and item.strip()]
        normalized_neg = [item.strip() for item in negatives if isinstance(item, str) and item.strip()]

        if len(normalized_pos) != half or len(normalized_neg) != half:
            raise ValueError(
                f"Gemini did not return exactly {half} positive and {half} negative strings."
            )

        return {"positive": normalized_pos, "negative": normalized_neg}

from flask import Flask, jsonify, request
from flask_cors import CORS
from sentence_transformers import SentenceTransformer
import torch

from category import Category, CategoryConfig, BLOCKMODE_STRICT, BLOCKMODE_WARN
from gemini import ExampleGenerator
from utils import decompose_url

from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs
from elevenlabs.play import play
from elevenlabs import VoiceSettings
import os
load_dotenv()
elevenlabs = ElevenLabs(
  api_key=os.getenv("ELEVENLABS_API_KEY"),
)

# audio = elevenlabs.text_to_speech.convert(
#     text="Maowww... I am a squoo. SquooberDASH. Hey, hello, welcome to Deerhacks",
#     voice_id="Nggzl2QAXh3OijoXD116",
#     model_id="eleven_monolingual_v1",
#     output_format="mp3_44100_128",
#     voice_settings=VoiceSettings(
#         stability=0.5,
#         similarity_boost=0.75,
#         style=0.0,
#         speed=0.7,
#     ),
# )

app = Flask(__name__)
CORS(app)

embedder = SentenceTransformer("Snowflake/snowflake-arctic-embed-xs")
example_generator = ExampleGenerator()

def embedding_fn(texts: list[str]) -> torch.Tensor:
    return torch.tensor(embedder.encode(texts), dtype=torch.float32)

configs: dict[str, CategoryConfig] = {}
blocklist_strict: dict[str, Category] = {}
blocklist_warn: dict[str, Category] = {}
allowlist_strict: dict[str, Category] = {}
allowlist_warn: dict[str, Category] = {}

def _parse_checktab_payload(data):
    if isinstance(data, dict):
        url, title = data.get("url", ""), data.get("title", "")
        if not url and not title:
            raise ValueError("Checktab payload must include at least 'url' or 'title' field.")
        return {
            "url": url.strip(),
            "title": title.strip(),
        }
    raise ValueError("Payload must be a JSON object.")
        
def _parse_description_payload(data):
    if isinstance(data, dict):
        name, desc, block_mode = data.get("name"), data.get("desc"), data.get("blockMode")
        if not name or not desc or not block_mode:
            raise ValueError("Description payload must include 'name', 'desc', and 'blockMode' fields.")
        if block_mode.strip() not in {BLOCKMODE_STRICT, BLOCKMODE_WARN}:
            raise ValueError(f"Invalid block mode: {block_mode}. Must be '{BLOCKMODE_STRICT}' or '{BLOCKMODE_WARN}'.")
        return {
            "name": name.strip(),
            "description": desc.strip(),
            "blockMode": block_mode.strip(),
        }
    raise ValueError("Payload must be a JSON object.")

def _parse_tags_payload(data):
    if isinstance(data, dict):
        name, pos, neg = data.get("name"), data.get("positiveTags", []), data.get("negativeTags", [])
        if not name:
            raise ValueError("Tags payload must include non-empty 'name' field.")
        if not isinstance(pos, list) or not isinstance(neg, list):
            raise ValueError("'positiveTags' and 'negativeTags' fields must be lists.")
        return {
            "name": name.strip(),
            "positiveTags": pos,
            "negativeTags": neg,
        }
    raise ValueError("Payload must be a JSON object.")

@app.route('/checktab', methods=['POST'])
def checktab():
    data = request.get_json(silent=True)
    try:
        payload = _parse_checktab_payload(data)
        url, title = payload["url"], payload["title"]
    except Exception as e:
        print(f"Error parsing checktab payload: {e}")
        return jsonify({"status": "error", "msg": "Invalid payload format."}), 400

    url_text = " ".join(word for word in decompose_url(url) if word)
    candidate_text = f"{title} {url_text}".strip()

    if not candidate_text:
        return jsonify({"status": "error", "msg": "Missing tab content."}), 400

    matched = None

    # TODO: consider allowlist categories as well, and how they should interact with blocklist categories if there's overlap or conflictd

    # iterate through strict blocklist first, then warn blocklist so that if
    # candidate matches any strict category, we can break early
    blocklist = list(blocklist_strict.values()) + list(blocklist_warn.values())
    for category in blocklist:
        if category.matches(candidate_text):
            matched = category.config
            break

    if matched:
        msg = f"Matched category: {matched.name}"
        block_mode = matched.block_mode
    else:
        msg = "No category match found."
        block_mode = "none"

    return jsonify(
        {
            "status": "success",
            "msg": msg,
            "matched": bool(matched),
            "blockMode": block_mode,
        }
    )

@app.route('/description', methods=['POST'])
def description():
    data = request.get_json(silent=True)
    try:
        payload = _parse_description_payload(data)
        desc, name, block_mode = payload["description"], payload["name"], payload["blockMode"]
    except Exception as e:
        print(f"Error parsing description payload: {e}")
        return jsonify({"status": "error", "msg": "Invalid payload format."}), 400

    cfg = CategoryConfig(name=name, initial_definition=desc, block_mode=block_mode)
    configs[cfg.name] = cfg

    tags: list[str] = []
    try:
        tags = example_generator.generate_examples(desc)
    except Exception as exc:
        print(f"Error generating edge-case tags: {exc}")
        return jsonify({"status": "error", "msg": "Failed to generate edge-case tags."}), 500

    return jsonify({
        "status": "success",
        "msg": "CategoryConfig initialized.",
        "categoryName": name,
        "tags": tags,
    })

@app.route('/tags', methods=['POST'])
def tags():
    data = request.get_json(silent=True)
    try:
        payload = _parse_tags_payload(data)
        name, positive_tags, negative_tags = payload["name"], payload["positiveTags"], payload["negativeTags"]
    except Exception as e:
        print(f"Error parsing tags payload: {e}")
        return jsonify({"status": "error", "msg": "Invalid payload format."}), 400
    
    # TODO: add ability to add categories to allowlist

    try:
        cfg = configs[name]
    except KeyError:
        return jsonify({"status": "error", "msg": f"No category config found for name: {name}"}), 404

    cfg.update_definitions(positive=positive_tags, negative=negative_tags)
    category = Category(cfg, embed_fn=embedding_fn)
    if cfg.block_mode == BLOCKMODE_STRICT:
        blocklist_strict[name] = category
    else:
        blocklist_warn[name] = category

    return jsonify(
        {
            "status": "success",
            "msg": "Category tags saved.",
            "categoryName": cfg.name,
            "positiveCount": len(cfg.positive_definitions),
            "negativeCount": len(cfg.negative_definitions),
        }
    )

if __name__ == '__main__':
    # play(audio)
    app.run(port=8000, host="0.0.0.0", debug=True)

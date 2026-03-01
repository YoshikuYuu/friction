from flask import Flask, jsonify, request
from flask_cors import CORS
from sentence_transformers import SentenceTransformer
import torch
import threading
import time
from pathlib import Path

from category import Category, CategoryConfig, BLOCKMODE_STRICT, BLOCKMODE_WARN
from config_store import ConfigStore, LISTTYPE_ALLOW, LISTTYPE_BLOCK
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

app = Flask(__name__)
CORS(app)

embedder = SentenceTransformer("Snowflake/snowflake-arctic-embed-xs")
example_generator = ExampleGenerator()

def embedding_fn(texts: list[str], query: bool) -> torch.Tensor:
    if query:
        return torch.as_tensor(embedder.encode(texts, prompt="query"), dtype=torch.float32)
    return torch.as_tensor(embedder.encode(texts), dtype=torch.float32)

configs: dict[str, CategoryConfig] = {}
blocklist_strict: dict[str, Category] = {}
blocklist_warn: dict[str, Category] = {}
allowlist_strict: dict[str, Category] = {}
allowlist_warn: dict[str, Category] = {}

store = ConfigStore(Path(__file__).parent / "data" / "categories.json")


def _bucket_for(list_type: str, block_mode: str) -> dict[str, Category]:
    if list_type == LISTTYPE_ALLOW and block_mode == BLOCKMODE_STRICT:
        return allowlist_strict
    if list_type == LISTTYPE_ALLOW and block_mode == BLOCKMODE_WARN:
        return allowlist_warn
    if list_type == LISTTYPE_BLOCK and block_mode == BLOCKMODE_WARN:
        return blocklist_warn
    return blocklist_strict


def _config_to_record(cfg: CategoryConfig, list_type: str) -> dict:
    return {
        "name": cfg.name,
        "initial_definition": cfg.initial_definition,
        "positive_definitions": cfg.positive_definitions,
        "negative_definitions": cfg.negative_definitions,
        "blockMode": cfg.block_mode,
        "listType": list_type,
    }


def _rebuild_runtime_from_store() -> None:
    configs.clear()
    blocklist_strict.clear()
    blocklist_warn.clear()
    allowlist_strict.clear()
    allowlist_warn.clear()

    for list_type, block_mode, record in store.iter_records():
        name = record["name"]
        initial_definition = record["initial_definition"]
        cfg = CategoryConfig(name=name, initial_definition=initial_definition, block_mode=block_mode)
        cfg.positive_definitions = record["positive_definitions"]
        cfg.negative_definitions = record["negative_definitions"]

        configs[name] = cfg
        _bucket_for(list_type, block_mode)[name] = Category(cfg, embed_fn=embedding_fn)

_rebuild_runtime_from_store()

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
            "listType": LISTTYPE_BLOCK, # TODO: allow this to be specified in the future if we add allowlist support in the UI
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

@app.route('/home', methods=['POST'])
def home():
    audio = elevenlabs.text_to_speech.convert(
        text="Hey there. Welcome to BlockedIn.",
        voice_id="Nggzl2QAXh3OijoXD116",
        model_id="eleven_monolingual_v1",
        output_format="mp3_44100_128",
        voice_settings=VoiceSettings(
            stability=0.5,
            similarity_boost=0.75,
            style=0.0,
            speed=0.7,
        ),
    )
    play(audio)
    return jsonify({"status": "success"})


@app.route('/checktab', methods=['POST'])
def checktab():
    data = request.get_json(silent=True)
    try:
        payload = _parse_checktab_payload(data)
        url, title = payload["url"], payload["title"]
    except Exception as e:
        print(f"Error parsing checktab payload: {e}")
        return jsonify({"status": "error", "msg": "Invalid payload format."}), 400

    # url_text = " ".join(word for word in decompose_url(url) if word)
    url_text = ""
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

    if block_mode == "warn":
        threading.Thread(target=warn_audio, daemon=True).start()
    if block_mode == "strict":
        threading.Thread(target=strict_audio, daemon=True).start()

    return jsonify(
        {
            "status": "success",
            "msg": msg,
            "matched": bool(matched),
            "blockMode": block_mode,
            # "blockMode": "warn",
        }
    )

def strict_audio():
    audio = elevenlabs.text_to_speech.convert(
        text="You blocked this page for a reason. Lock back in, nerd.",
        voice_id="Nggzl2QAXh3OijoXD116",
        model_id="eleven_monolingual_v1",
        output_format="mp3_44100_128",
        voice_settings=VoiceSettings(
            stability=0.5,
            similarity_boost=0.75,
            style=0.0,
            speed=0.7,
        ),
    )
    play(audio)

def warn_audio():
    time.sleep(0.3)  # only blocks this thread

    audio = elevenlabs.text_to_speech.convert(
        text="Hey. Are you supposed to be on this page?",
        voice_id="Nggzl2QAXh3OijoXD116",
        model_id="eleven_monolingual_v1",
        output_format="mp3_44100_128",
        voice_settings=VoiceSettings(
            stability=0.5,
            similarity_boost=0.75,
            style=0.0,
            speed=0.7,
        ),
    )
    play(audio)

@app.route('/description', methods=['POST'])
def description():
    data = request.get_json(silent=True)
    try:
        payload = _parse_description_payload(data)
        desc, name, block_mode, list_type = payload["description"], payload["name"], payload["blockMode"], payload["listType"]
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
        "msg": f"CategoryConfig initialized for {name} in {list_type} with block mode {block_mode}.",
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

    list_type = LISTTYPE_BLOCK # TODO: allow this to be specified in the future

    cfg.update_definitions(positive=positive_tags, negative=negative_tags)
    category = Category(cfg, embed_fn=embedding_fn)
    _bucket_for(list_type, cfg.block_mode)[name] = category
    configs[name] = cfg
    store.upsert_record(
        name=cfg.name,
        list_type=list_type,
        block_mode=cfg.block_mode,
        record=_config_to_record(cfg, list_type=list_type),
    )

    return jsonify(
        {
            "status": "success",
            "msg": "Category tags saved.",
            "categoryName": cfg.name,
            "positiveCount": len(cfg.positive_definitions),
            "negativeCount": len(cfg.negative_definitions),
        }
    )


@app.route('/configs', methods=['GET'])
def get_configs():
    return jsonify({"status": "success", "configs": store.configs_as_list()})


@app.route('/config', methods=['DELETE'])
def delete_config():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    list_type = (data.get("listType") or "").strip()
    block_mode = (data.get("blockMode") or "").strip()

    if not name:
        return jsonify({"status": "error", "msg": "Missing category name."}), 400
    if block_mode not in {BLOCKMODE_STRICT, BLOCKMODE_WARN}:
        return jsonify({"status": "error", "msg": "Invalid blockMode."}), 400
    if list_type not in {LISTTYPE_BLOCK, LISTTYPE_ALLOW}:
        return jsonify({"status": "error", "msg": "Invalid listType."}), 400

    deleted = store.delete_record(name=name, list_type=list_type, block_mode=block_mode)
    if not deleted:
        return jsonify({"status": "error", "msg": "Category not found."}), 404

    _rebuild_runtime_from_store()
    return jsonify({"status": "success", "msg": "Category removed."})

if __name__ == '__main__':
    # play(audio)
    app.run(port=8000, host="0.0.0.0", debug=True)

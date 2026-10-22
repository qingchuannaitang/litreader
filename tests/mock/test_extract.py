"""Mock layer: extraction with a fake LLM transport (no network)."""
import json

from litreader.analysis.extract import extract
from litreader.analysis.validator import validate
from litreader.llm.config import parse_config
from litreader.parse.blocks import Block

BLOCKS = [Block("title", 1, None, "标题", order=0), Block("text", 1, None, "共纳入 89 名老年人。", order=1)]
CFG = parse_config({"providers": {"ds": {"protocol": "openai_compatible", "base_url": "https://x.example",
                    "model": "user-model", "key_env": "K", "json_mode": True, "max_tokens": 1000,
                    "extra_body": {"thinking": {"type": "disabled"}}}}, "stations": {"extract": ["ds"]}})


def test_extract_sends_config_fields_and_validates():
    seen = []

    def transport(url, headers, body, timeout):
        seen.append(json.loads(body))
        out = {"facts": [{"field": "sample_size_total", "value": "89", "context": "共纳入 89 名老年人",
                          "block_id": "b1", "physical_page": 1, "label": "PAPER"},
                         {"field": "funding", "value": "国家基金", "context": "国家基金资助", "block_id": "b1",
                          "physical_page": 1, "label": "PAPER"}], "claims": []}
        return 200, json.dumps({"choices": [{"message": {"content": json.dumps(out)}}],
                                "usage": {"prompt_tokens": 10, "completion_tokens": 5}}).encode()

    merged, runs, n = extract(BLOCKS, CFG.chain("extract"), transport, {"K": "k"})
    req = seen[0]
    assert req["thinking"] == {"type": "disabled"} and req["response_format"] == {"type": "json_object"}
    assert req["max_tokens"] == 1000 and "[b1|p1|text]" in req["messages"][1]["content"]
    assert n == 1 and runs[0]["usage"]["prompt_tokens"] == 10
    r = validate(merged, BLOCKS)
    assert r.counts["facts_paper_ok"] == 1 and r.rejected[0]["item"]["field"] == "funding"


def test_extract_bad_json_is_not_silently_ok():
    def transport(url, headers, body, timeout):
        return 200, json.dumps({"choices": [{"message": {"content": "not json"}}]}).encode()
    merged, runs, _ = extract(BLOCKS, CFG.chain("extract"), transport, {"K": "k"})
    assert merged["facts"] == [] and validate(merged, BLOCKS).enforced_unknown

import json
from pathlib import Path
from services.bot.intent import Intent
import pytest
path = Path(__file__).parent / "intent_classifier_test_cases.json"
path = Path(__file__).parent / "intent_test_cases.json"
path = Path(__file__).parent / "intent_test_cases_added_few_shot_examples.json"
path = Path(__file__).parent / "intent_test_cases_batch2.json"

test_cases = json.loads(path.read_text())

@pytest.fixture(scope="session", autouse=True)
def save_results():
    yield  # runs after all tests in the session finish
    path.write_text(json.dumps(test_cases, indent=2, ensure_ascii=False), encoding="utf-8")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", test_cases, ids=[c["id"] for c in test_cases])
async def test_intent_classification(case: dict):
    intent = Intent()
    result = await intent.classify(
        conversation_history=case.get("history") or [],
        user_query=case["message"],
    )
    case["intent"] = result['intent']
    case["reasoning"] = result['reasoning']
    assert result["intent"] == case["expected_intent"]

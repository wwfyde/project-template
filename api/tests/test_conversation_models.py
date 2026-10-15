from datetime import UTC, datetime

from openai.types.responses.response import Response

from api.models.conversation import OpenaiResponse


def test_openai_response_from_api_response() -> None:
    api_response = Response.model_validate(
        {
            "id": "resp_test",
            "object": "response",
            "created_at": 1_753_248_600,
            "completed_at": 1_753_248_601,
            "status": "completed",
            "model": "gpt-5.4",
            "output": [
                {
                    "id": "rs_test",
                    "type": "reasoning",
                    "summary": [],
                    "status": "completed",
                },
                {
                    "id": "msg_test",
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Hello!",
                            "annotations": [],
                        }
                    ],
                },
            ],
            "parallel_tool_calls": True,
            "previous_response_id": "resp_previous",
            "reasoning": {"effort": "medium", "summary": None},
            "store": True,
            "tool_choice": "auto",
            "tools": [],
            "usage": {
                "input_tokens": 12,
                "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                "output_tokens": 6,
                "output_tokens_details": {"reasoning_tokens": 0},
                "total_tokens": 18,
            },
        }
    )

    record = OpenaiResponse.from_api_response(
        api_response,
        conversation_id="conversation_test",
        message_id="message_test",
    )

    assert record.id == "resp_test"
    assert record.conversation_id == "conversation_test"
    assert record.message_id == "message_test"
    assert record.previous_response_id == "resp_previous"
    assert record.status == "completed"
    assert record.model == "gpt-5.4"
    assert record.api_created_at == datetime.fromtimestamp(1_753_248_600, tz=UTC)
    assert record.api_completed_at == datetime.fromtimestamp(1_753_248_601, tz=UTC)
    assert record.store is True
    assert record.usage == {
        "input_tokens": 12,
        "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
        "output_tokens": 6,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": 18,
    }
    assert [item.type for item in record.items] == ["reasoning", "message"]
    assert record.items[0].item_id == "rs_test"
    assert record.items[1].role == "assistant"
    assert record.items[1].data["content"][0]["text"] == "Hello!"
    assert record.raw_response["output"][0]["type"] == "reasoning"


def test_openai_response_accepts_raw_mapping() -> None:
    record = OpenaiResponse.from_api_response(
        {
            "id": "resp_mapping",
            "object": "response",
            "created_at": 1_753_248_600,
            "model": "gpt-5.4",
            "output": [
                {
                    "type": "function_call",
                    "call_id": "call_test",
                    "name": "get_weather",
                    "arguments": '{"city":"Shanghai"}',
                }
            ],
        },
        conversation_id="conversation_test",
    )

    assert record.items[0].item_id is None
    assert record.items[0].call_id == "call_test"
    assert record.items[0].name == "get_weather"
